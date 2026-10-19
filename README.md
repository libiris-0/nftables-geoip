# nftables-geoip

nftables-geoip 为每个 IP 网段分配一个国家编码，再把按名称书写的区域规则编译成类别。产物是 nftables 的三张 map：

- `geo4`、`geo6`：地址 → 国家编码。
- `geoclass`：国家编码 → 类别。

国家编码按洲分块，洲内按海缆和陆地接壤排序。同一条海缆连接的国家，编码彼此相邻。因此一片区域通常只需要几个区间或掩码就能覆盖。

区域用名称书写，例如 `CN + JP`、`@EU - FR`，不需要手写编码。

本项目只使用 Python 3.14 及以上版本的标准库，没有第三方依赖。

## 文档

- [SPEC.md](SPEC.md)：行为规范，包括输入、编码规则、输出格式和规则语言。
- [examples/](examples/)：示例规则 `rules.txt`，以及使用三张 map 的示例规则集 `geomark.nft`。
- [deploy/](deploy/)：加载脚本 `geoipctl` 和 systemd 单元，负责从 Release 下载编译结果并加载进 nftables。

## 用法

```sh
# 构建国家编码和 IP 映射。与规则无关，多个规则文件可以共用。GeoLite2 City 约需 30 秒。
python3 -m nftables_geoip build --geoip GeoLite2-City-CSV/ --countries 0x800-0xfff \
    --links links.txt --out build/

# 编译一个规则文件，输出一个 nft 脚本。nft -f 加载时一次替换三张 map。
python3 -m nftables_geoip compile build/ examples/rules.txt --table "inet routing" -o examples.nft

# 查看表达式选中了哪些国家，以及需要几个区间和掩码。
python3 -m nftables_geoip query build/ --rules examples/rules.txt 'ESEA - JP'
```

### 输入

- **GeoIP 数据**：[GeoLite2 City](https://dev.maxmind.com/geoip/geolite2-free-geolocation-data) 的 CSV 目录。下载需要 MaxMind 账号。
- **`--countries`**：国家编码占用的区间，必须是一个对齐的 2 的幂块，例如 `0x800-0xfff`。
- **`links.txt`**：可选，记录国家之间的连接，每行一条，例如 `cable:<id> 国家…` 或 `border A B`。缺省时只按地理距离排序。格式见 SPEC 1.2，文件内容自行生成。
- **规则文件**：区域规则，写法见下一节。
- **`--table`**：三张 map 所在的表，例如 `"inet filter"`。

### 规则

```
ESEA     = CN + JP + SG       # 定义区域
default  -> 0x200             # 没有被任何规则选中的国家
@EU - FR -> 0x301             # 例外可以写成差集
FR       -> 0x302
DE       -> 0x303 !           # 也可以用 ! 显式覆盖前面的规则
ESEA     -> 0x212
```

表达式由三种元素组成：国家（两个大写字母）、`@洲`（AF、AN、AS、EU、NA、OC、SA 和 ZZ）和已定义的名称。运算符有 `+`（并）、`-`（差）、`&`（交）和 `~`（补），可以用括号分组。

两条规则的类别不同而选中的国家重叠时，编译报错并列出冲突的国家。在后一条规则末尾加上 `!`，即可显式覆盖前一条。

### 在 nftables 中使用

编译结果只替换三张 map 的元素，不创建 map。三张 map 的名称、键和值见 SPEC 6.1。

[examples/geomark.nft](examples/geomark.nft) 是一个规则集示例：只修改 mark 和 ct mark 的低 12 位，并在 ct mark 中保存类别。

[deploy/](deploy/) 中的 systemd 单元在 nftables.service 启动后加载编译结果，并定时从 Release 更新。

## 测试

```sh
python3 -I tests/run.py
```

测试只使用 `tests/` 中的合成数据，即一个由 26 个国家组成的虚构世界。加载脚本的集成测试在非特权的 user/network namespace 中运行，不改动宿主网络。详见 [tests/README.md](tests/README.md)。

## 许可

[MIT](LICENSE)
