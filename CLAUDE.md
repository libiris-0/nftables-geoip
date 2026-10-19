# nftables-geoip

nftables-geoip 把 IP 网段映射到国家编码，再把按名称书写的区域规则编译成类别。产物是 nftables 的三张 map。

## 规则

- **SPEC.md 是行为的唯一依据。** 修改可观察行为（输入、输出、编码和规则语言）时，先改 SPEC，再改代码和测试。SPEC 用声明式写法，只写定义、规则和不变量，不写实现过程和原因。未定义和实现定义的行为在 SPEC 中明确标出。
- **map 的类型、链和规则、mark 各位的用途、priority 的用法以及类别编号的分配，都属于规则集**，不写进 SPEC 和代码。`examples/` 和 `deploy/` 是使用示例和部署脚本，不是产物。
- **只使用 Python 标准库**，要求 Python 3.14 或更高版本，不加第三方依赖。
- **真实数据一律不进本仓库**，包括 GeoIP 数据及其派生文件（build 目录和 nft 脚本）、连接数据和真实规则。本仓库公开，而这些数据大多不允许再分发。测试只使用 `tests/` 中的合成数据。
- 文档用中文。代码和配置（包括 systemd 单元文件和 CI 工作流）中的注释、标识符和程序输出用英文。测试的检查描述可以用中文。中文排版遵循[《中文文案排版指北》](https://github.com/sparanoid/chinese-copywriting-guidelines)。

## 测试

- 单元测试按 SPEC 章节组织。
- 每项行为同时验证生效条件，以及旁路或拒绝条件。
- 未定义和实现定义的行为不固定预期。
- 单元测试不依赖 nft，保持这一点。
- 网络操作只在测试创建的临时 user/network namespace 中进行，不修改宿主的规则和 sysctl。

## 命令

```sh
python3 -I tests/run.py
python3 -I tests/run.py unit
```

完整的流程见 `.github/workflows/test.yml`，说明见 `tests/README.md`。
