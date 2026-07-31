# 部署说明

## 适用范围

本说明用于将 BZP Phase III规划探索工具迁移至新的 Linux 服务器。应用为 Streamlit 服务，推荐仅监听 `127.0.0.1`，由公司批准的反向代理、网关或容器入口提供 HTTPS 和外部访问。Cloudflare 不是必需组件。

## 交付物

IT 将收到两部分内容：

1. 本 Git 仓库：应用源代码、依赖清单、配置模板和 systemd 模板。
2. 私下交付的运行资产包：模型资产、受控参考文件和 SHA256 校验清单。

私下交付的资产必须解压到应用安装目录，保留清单中的相对路径。

## 服务器要求

- Linux 服务器，建议 Python 3.12。
- 可创建专用服务账户、应用目录、状态目录和受控环境变量文件。
- 可由公司现有反向代理或网关转发至本机 `127.0.0.1:8517`。
- 不应将 Streamlit 端口直接暴露至公网。

## 安装步骤

1. 克隆仓库到 IT 指定的安装目录，例如 `/opt/bzp-phase3-demo`。
2. 在安装目录创建 Python 虚拟环境，并安装依赖：

```bash
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

3. 将私下交付的运行资产包解压至安装目录；执行 SHA256 校验清单。
4. 创建状态目录，例如 `/var/lib/bzp-phase3-demo`，并授权服务账户读写。
5. 以 `config/production.env.example` 为模板创建受限环境文件，例如 `/etc/bzp-phase3-demo/bzp-phase3-demo.env`。真实用户名、密码和邮件密钥不得提交到 Git。
6. 将 `deploy/bzp-phase3-demo.service.example` 复制为 systemd 服务文件，替换 `__SERVICE_USER__`、`__SERVICE_GROUP__`、`__INSTALL_DIR__`、`__ENV_FILE__` 和 `__VENV_DIR__`。
7. 执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bzp-phase3-demo
sudo systemctl status bzp-phase3-demo
curl -f http://127.0.0.1:8517/_stcore/health
```

8. 由 IT 的反向代理或网关将正式 HTTPS 域名转发至 `http://127.0.0.1:8517`，并支持 WebSocket 转发。

## 登录与邮件反馈

应用内登录由环境变量 `SPONSOR_DEMO_USERNAME` 和 `SPONSOR_DEMO_PASSWORD` 控制。Git 仓库和私下运行资产包均不包含真实值；IT 必须将项目维护人通过安全渠道提供的值写入受限环境文件。配置为相同值后，甲方可继续使用同一组用户名和密码。

反馈会始终先写入本地状态目录。若需要邮件提醒和自动回执，还必须：

1. 在受限环境文件中启用 `SPONSOR_EMAIL_ENABLED=1`，并填写 Gmail 相关配置。
2. 以受限权限保存 Gmail 应用密码文件，并令 `SPONSOR_GMAIL_APP_PASSWORD_FILE` 指向该文件。
3. 由 `deploy/bzp-feedback-email.service.example` 和 `deploy/bzp-feedback-email.timer.example` 创建对应的 systemd 服务和定时器。
4. 启用定时器：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bzp-feedback-email.timer
sudo systemctl status bzp-feedback-email.timer
```

定时器每分钟处理一次待发送邮件。部署后可由 IT 使用 `scripts/process_feedback_email_outbox.py --send-test-to <recipient>` 发送测试邮件，并检查 systemd journal。

## 运行状态与备份

`SPONSOR_DEMO_LOCAL_DATA_ROOT` 下保存反馈数据库、附件和更新日志。建议纳入公司备份策略。应用日志默认进入 systemd journal，可由 IT 按现有日志策略收集。

## 验收

确认外网 HTTPS 地址可打开，随后完成：登录、运行模拟、查看二期人群洞察、下载报告、提交文字反馈和上传图片。服务重启后应能自动恢复，反馈历史仍可读取。
