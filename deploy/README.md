# 部署

加载脚本 `geoipctl` 从一个 GitHub 仓库的最新 Release 下载 nft 脚本，并加载进内核。Release 中需要有名为 `<配置名>.nft.gz` 的文件，内容是用 gzip 压缩的 compile 输出。一个 Release 可以包含多个配置名的文件。

`geoipctl` 只替换三张 map 的元素，加载前三张 map 必须已经存在，定义方法可以参考 [../examples/geomark.nft](../examples/geomark.nft)。

## 文件

- `geoipctl`：安装到 `/usr/local/libexec/nftables-geoip/`，由 systemd 单元调用。提供两个子命令：`restore` 加载本地副本；`update` 在有新 Release 时下载并加载，再替换本地副本。
- `systemd/nftables-geoip.service`：nftables.service 每次启动（包括重启）后执行 `restore`。
- `systemd/nftables-geoip-update.service` 和 `.timer`：执行 `update`。时间为开机 30 分钟后，以及每周三和周六 04:00，每次随机推迟至多 1 小时。系统繁忙时跳过本次。

依赖 bash、curl、jq、gzip 和 nft，需要 systemd 250 和 Linux 5.13 或更高版本。

## 安装

```sh
install -D -m 755 geoipctl /usr/local/libexec/nftables-geoip/geoipctl
install -m 644 systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl enable nftables-geoip.service nftables-geoip-update.timer
```

安装后完成以下设置：

1. 准备一个 fine-grained token，只授予 Release 所在仓库 Contents 的读权限。用本机的密钥把它加密成 systemd 凭据：

   ```sh
   systemd-creds encrypt --name=token -p - -
   ```

   粘贴 token，按 Ctrl-D 结束输入。命令输出一段以 `SetCredentialEncrypted=token:` 开头的设置。
2. 运行 `systemctl edit nftables-geoip-update.service`，在 `[Service]` 下写入仓库、本机的配置名和上一步的输出：

   ```
   [Service]
   Environment=REPO=owner/name CONFIG=home
   SetCredentialEncrypted=token: \
           k6iUCUh0RJCQyvL8k8q1UyAAAAABAAAADAAAABAAAAC1lFmbWAqWZ8dCCQkAAAAAgAAAA…
   ```

   设置保存在 drop-in 中，重新安装单元文件时不会被覆盖。加密的 token 只能在本机解密。
3. 手动执行第一次更新：`systemctl start nftables-geoip-update.service`。

## 行为

**update** 查询 `REPO` 的 `releases/latest` 的 tag，与本地记录相同时直接结束。否则下载 Release 中的 `<配置名>.nft.gz`，用 `nft -f` 加载。加载成功后，替换本地副本并记录新的 tag。

**restore** 在本地副本存在时用 `nft -f` 加载它。本地副本不存在时跳过，等待第一次 update。

任何一步失败，内核中的数据和本地副本都保持原样。`restore` 和 `update` 不会同时运行。

以 GeoLite2 City 为例，一次加载约需 7 秒，内存峰值约 1.4 GB。update 服务的内存上限是 2 GB，超过时这次加载失败。系统的内存或 CPU 压力较高时，本次 update 跳过，等下一次定时。

开机时，`nftables-geoip.service` 在 nftables.service 启动后加载本地副本。加载完成前，三张 map 为空。
