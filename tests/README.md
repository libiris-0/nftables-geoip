# 测试

```sh
python3 -I tests/run.py
python3 -I tests/run.py unit
python3 -I tests/run.py --output /path/to/new/directory
```

不指定套件时运行全部两套。各套件在各自的进程中并行运行。

## 依赖

- Python 3.14，只用标准库。
- `geoipctl` 套件另需 Linux，并允许非特权 user namespace。
- `geoipctl` 套件另需 `nft` 和 `ip`，以及 `geoipctl` 本身依赖的 bash、curl、jq 和 gzip。

Ubuntu 24.04 及以后的版本默认用 AppArmor 限制非特权 user namespace，需要先执行：

```sh
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
```

完整流程见 [.github/workflows/test.yml](../.github/workflows/test.yml)。

## 套件

| 套件 | 文件 | 内容 |
| --- | --- | --- |
| `unit` | `test_*.py` | SPEC 第 1 节至第 7 节，不需要 nft |
| `geoipctl` | `geoipctl.py` | 加载脚本 `deploy/geoipctl` 的 restore 和 update |

`unit` 的每个文件开头注明对应的 SPEC 章节。

## 合成数据

`world.py` 构造一个由 26 个国家组成的虚构世界，包括 GeoLite2 City CSV 目录和 `links.txt`。其中有几种特殊网段，用来覆盖 SPEC 1.1 的回退和重叠网段的丢弃。

## geoipctl 套件

测试进程先进入自己的 user/network namespace，宿主的规则和网络保持不变。随后：

1. 用合成数据执行 build，再用 `examples/rules.txt` 执行 compile，得到 nft 脚本。
2. 加载 `examples/geomark.nft`，定义三张 map。这一步同时确认示例规则集能被 nft 解析，并能装入 compile 的输出。
3. 在本地起一个 HTTP 服务，模拟 GitHub API 的 `releases/latest` 和 Release 下载，并记录每个请求的 `Authorization`。
4. 用环境变量 `NFTABLES_GEOIP_STATE` 和 `NFTABLES_GEOIP_API` 把状态目录和 API 地址指向临时目录和本地服务，依次运行各个场景。

每个场景检查内核中 `geo4` 的元素、本地副本和记录的 tag。失败场景包括下载不完整、查询 Release 失败、Release 中没有本机配置的文件和 nft 无法加载。每个失败场景都要求这三项保持原样，并且没有残留的临时文件。

## 结果

结果默认写入新建的临时目录，也可以用 `--output` 指定一个新目录。每个套件写一个 `<套件>.json`：

| 字段 | 内容 |
| --- | --- |
| `counts` | `pass`、`fail` 和 `error` 的用例数 |
| `cases` | 每个用例的分组、名称、状态，以及失败时的异常信息 |

每个套件结束后，运行器按分组打印用例的状态。`unit` 的分组是测试文件，一个测试方法计为一个用例，其中任何一个子测试失败，这个用例就失败。`geoipctl` 的分组是场景，一项检查计为一个用例。

`fail` 表示结果与预期不符，`error` 表示测试代码或环境出错。有 `fail` 或 `error` 时，运行器以非零状态退出。
