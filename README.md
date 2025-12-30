# VoxRadar 1.0

一个面向**产品调研**的轻量级前后端一体应用。前端为单页页面，后端提供数据采集与分析 API，并通过 WebSocket 推送运行状态与日志。

## 目录结构
- 前端页面：`index_V1.0.html`
- 后端服务：`api/`（FastAPI）
- 入口路由：后端根路径 `/` 会直接返回前端页面

## 环境要求
- Python 3.11+
- 推荐包管理：uv 或原生 venv
- Playwright 浏览器驱动（用于采集）

## 安装依赖
使用 uv（推荐）：

```bash
uv sync
uv run playwright install
```

使用原生 venv：

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install
```

## 启动后端
方式一（模块方式，默认端口 8090）：

```bash
python -m api.main
```

方式二（自定义端口）：

```bash
uvicorn api.main:app --port 8090 --reload
```

启动成功后访问：
- 前端页面：`http://localhost:8090/`
- API 基址：`http://localhost:8090/api`

前端会自动探测后端端口并连接以下接口：
- 运行状态：`GET /api/crawler/status` 与 `WS /api/ws/status`
- 实时日志：`GET /api/crawler/logs` 与 `WS /api/ws/logs`
- 启动任务：`POST /api/crawler/start`
- 停止任务：`POST /api/crawler/stop`
- 报告下载：`GET /api/data/download/{path}`

## 常见问题
- 修改前端文件名不会影响后端启动，但后端首页路由默认查找 `index_V1.0.html`。如需改名，请同步调整 `api/main.py` 中首页路由的文件路径。
- 若后端未能自动被前端检测到，前端会回退到 `http://localhost:8090/api`。

## 许可证
本项目代码基于根目录下的 LICENSE 约束，仅供学习与研究使用，不得用于商业用途。

---

### 📚 其他
- **常见问题**：[MediaCrawler 完整文档](https://nanmicoder.github.io/MediaCrawler/)
- **爬虫入门教程**：[CrawlerTutorial 免费教程](https://github.com/NanmiCoder/CrawlerTutorial)
- **新闻爬虫开源项目**：[NewsCrawlerCollection](https://github.com/NanmiCoder/NewsCrawlerCollection)


## 📚 参考

- **小红书签名仓库**：[Cloxl 的 xhs 签名仓库](https://github.com/Cloxl/xhshow)
- **小红书客户端**：[ReaJason 的 xhs 仓库](https://github.com/ReaJason/xhs)
- **短信转发**：[SmsForwarder 参考仓库](https://github.com/pppscn/SmsForwarder)
- **内网穿透工具**：[ngrok 官方文档](https://ngrok.com/docs/)


# 免责声明
<div id="disclaimer"> 

## 1. 项目目的与性质
本项目（以下简称“本项目”）是作为一个技术研究与学习工具而创建的，旨在探索和学习网络数据采集技术。本项目专注于自媒体平台的数据爬取技术研究，旨在提供给学习者和研究者作为技术交流之用。

## 2. 法律合规性声明
本项目开发者（以下简称“开发者”）郑重提醒用户在下载、安装和使用本项目时，严格遵守中华人民共和国相关法律法规，包括但不限于《中华人民共和国网络安全法》、《中华人民共和国反间谍法》等所有适用的国家法律和政策。用户应自行承担一切因使用本项目而可能引起的法律责任。

## 3. 使用目的限制
本项目严禁用于任何非法目的或非学习、非研究的商业行为。本项目不得用于任何形式的非法侵入他人计算机系统，不得用于任何侵犯他人知识产权或其他合法权益的行为。用户应保证其使用本项目的目的纯属个人学习和技术研究，不得用于任何形式的非法活动。

## 4. 免责声明
开发者已尽最大努力确保本项目的正当性及安全性，但不对用户使用本项目可能引起的任何形式的直接或间接损失承担责任。包括但不限于由于使用本项目而导致的任何数据丢失、设备损坏、法律诉讼等。

## 5. 知识产权声明
本项目的知识产权归开发者所有。本项目受到著作权法和国际著作权条约以及其他知识产权法律和条约的保护。用户在遵守本声明及相关法律法规的前提下，可以下载和使用本项目。

## 6. 最终解释权
关于本项目的最终解释权归开发者所有。开发者保留随时更改或更新本免责声明的权利，恕不另行通知。
</div>
