### 签名服务安装、运行（建议在内网服务器或者开启防火墙服务器单独部署，以免暴露助记词）
```bash
  cd signing_server
  python3 -m venv .venv
  source .venv/bin/activate

  pip install -r requirements.txt

 # 开发模式
  uvicorn main:app --host 0.0.0.0 --port 9090
```


### 使用 Systemd 服务 安全地注入环境变量（钱包私钥）
1. 创建一个安全的密钥文件：
创建一个只有 root 用户或运行服务的特定用户才能读取的文件。
这个文件不叫 .env，可以叫任何名字，并且放在一个安全的位置，例如 /etc/signing_server/secret.env。

```bash
# 创建目录
sudo mkdir -p /etc/signing_server

# 创建文件并写入密钥
# 注意 " " 引号，以处理包含空格的助记词
sudo bash -c 'echo "MASTER_MNEMONIC_FOR_SIGNING=\"word1 word2 ...\"" > /etc/signing_server/secret.env'

# 设置严格的权限：只有所有者（root）可读写
sudo chmod 600 /etc/signing_server/secret.env
```

2.创建一个 systemd 服务文件：
在 /etc/systemd/system/ 目录下创建一个名为 signing-server.service 的文件。

```bash
sudo vim /etc/systemd/system/signing-server.service
```
将以下内容粘贴进去，并根据您的实际路径进行修改

```Ini

[Unit]
Description=Secure Signing Service for Payment Bot
After=network.target

[Service]
# 替换为实际运行服务的用户和组
User=root 
Group=root

# 设置工作目录
WorkingDirectory=/www/tron-payment-sdk/signing_server

# [核心] 从安全的文件加载环境变量
EnvironmentFile=/etc/signing_server/secret.env

# 替换为您的虚拟环境中 uvicorn 的绝对路径
ExecStart=/www/tron-payment-sdk/signing_server/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 9090

Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target

```

3.管理服务：

```bash
# 重新加载 systemd 配置，让它识别新服务
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start signing-server

# 查看服务状态，检查是否有错误
sudo systemctl status signing-server

# 设置开机自启
sudo systemctl enable signing-server
```