# 🌸 小红书笔记采集器

一款基于 Flask + Playwright 的小红书笔记采集工具，支持粘贴分享链接即可自动提取标题、正文、互动数据等，导出为 Excel。

## ✨ 功能

- 粘贴小红书分享文本或链接，自动采集笔记数据
- 自动分类 Hook 类型（疑问型、数字型、悬念型等）
- 数据去重检测
- 脏数据审计 & 一键修复
- 导出为格式化的 `.xlsx` 文件
- 持久化登录（扫码一次，后续免登录）

## 📋 环境要求

- **Python 3.10+**
- **操作系统**：macOS / Windows / Linux
- 需要能打开浏览器窗口（首次扫码登录用）

## 🚀 安装 & 启动

```bash
# 1. 克隆项目
git clone https://github.com/zhilianyang06-jpg/xhs-scraper.git
cd xhs-scraper

# 2. 安装依赖
pip install -r requirements.txt

# 3. 安装 Playwright 浏览器
playwright install chromium

# 4. 启动
python app.py
```

启动后浏览器打开 **http://localhost:5001** 即可使用。

### macOS 快捷方式（可选）

项目自带管理脚本，支持后台运行：

```bash
bash xhs.sh start    # 启动（自动打开浏览器）
bash xhs.sh stop     # 停止（可选导出数据到桌面）
bash xhs.sh restart  # 重启
bash xhs.sh status   # 查看状态
```

> ⚠️ `xhs.sh` 中 Python 路径默认为 `/opt/anaconda3/bin/python3.12`，如果你用的是其他 Python，请修改脚本第 5 行的 `PYTHON=` 路径。

## 📖 使用流程

1. **首次使用**：点击页面上的「扫码登录」，用小红书 App 扫描弹出的二维码
2. **采集笔记**：粘贴小红书分享文本（或链接）到输入框，点击采集
3. **导出数据**：点击「导出 Excel」下载采集结果

## 📁 项目结构

```
├── app.py             # Flask 服务器（路由、Excel 读写）
├── scraper.py         # Playwright 采集 & 登录逻辑
├── xhs.sh             # macOS 管理脚本
├── requirements.txt   # Python 依赖
├── templates/         # 前端页面（Flask 模板）
├── data/              # 采集数据（Excel 文件）
└── session/           # 登录态存储（自动生成，勿删）
```

## ❓ 常见问题

**Q: 提示「登录已过期」？**
A: 小红书 cookie 有效期有限，重新点击「扫码登录」即可。

**Q: `localhost:5001` 打不开？**
A: 服务没在运行，重新执行 `python app.py` 或 `bash xhs.sh start`。

**Q: 别人能访问我的采集器吗？**
A: 不能。`localhost` 只限本机访问，每个人需要在自己电脑上运行。

## ⚠️ 免责声明

本工具仅供个人学习研究使用，请遵守小红书平台的使用条款，勿用于大规模爬取或商业用途。
