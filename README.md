# taoguba-crawler-skill

淘股吧抓取与复盘项目。当前已经改造成可长期运行的定时任务：

- 每天固定时间执行一次，默认 19:00
- 抓取淘股吧论坛或首页推荐
- 生成 `output/` 下的 JSON、HTML 和最终发送用 Markdown
- 调用 DashScope 兼容接口做中文复盘分析
- 通过 picoclaw 推送到飞书
- 支持 `testsend` / `testsend-live`
- 支持 `deploy.py` 部署到远端
- 支持 PM2 托管主进程

## 目录

- [main.py](D:/dev/github/taoguba-crawler-skill/main.py): 每日定时主进程
- [app_common.py](D:/dev/github/taoguba-crawler-skill/app_common.py): `.env`、代理、通知、日志公共能力
- [scripts/taoguba_report.py](D:/dev/github/taoguba-crawler-skill/scripts/taoguba_report.py): 报告生成与通知发送
- [scripts/crawler_bbs.py](D:/dev/github/taoguba-crawler-skill/scripts/crawler_bbs.py): 股吧论坛抓取
- [scripts/crawler_home.py](D:/dev/github/taoguba-crawler-skill/scripts/crawler_home.py): 首页推荐抓取
- [deploy.py](D:/dev/github/taoguba-crawler-skill/deploy.py): 上传部署脚本
- [ecosystem.config.js](D:/dev/github/taoguba-crawler-skill/ecosystem.config.js): PM2 配置

## 环境变量

复制 [`.env.example`](D:/dev/github/taoguba-crawler-skill/.env.example) 为 `.env`，至少配置这些项：

```env
COOKIE=你的淘股吧 Cookie
SCRAPE_TIME=19:00
TAOGUBA_SOURCE=bbs

DASHSCOPE_API_KEY=你的 DashScope Key
DASHSCOPE_BASE_URL=https://coding.dashscope.aliyuncs.com/v1
DASHSCOPE_MODEL=qwen3.5-plus

PICOCLAW_EXE=/home/nuonuo/picoclaw-linux-amd64
PICOCLAW_CHANNEL=feishu
```

可选：

```env
HTTP_PROXY=127.0.0.1:2334
HTTPS_PROXY=127.0.0.1:2334
```

## 安装

```bash
python -m pip install -r requirements.txt
```

建议使用虚拟环境：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## 使用

TASK06 sample 小闭环：

```bash
make crawl-sample
```

该命令只抓少量列表页、少量详情页和评论第一页，写入 `data/tgb-sample.sqlite`，用于验证小样本闭环；它不是 full 全量抓取。

TASK06 incremental 增量模式：

```bash
make crawl-incremental
```

该命令从最新列表页开始扫描少量页，发现新帖、抓取详情，并复查近期评论变化；它仍然不是 full 全量抓取。

TASK07 backfill sample：

```bash
make crawl-backfill-sample
```

该命令从当前最后页开始倒序抓少量历史页面，并按上限补评论分页；它仍然不是长期 full 全量抓取。

TASK09 受控 full trial：

```bash
make crawl-full-trial
```

该命令使用 list/article/comment_page 队列做小范围 full 试运行；它仍然带有 `manual_approval_required` 闸门，不是 TASK10 长期 full。

TASK11 反爬熔断：

当前已接入错误页检测。若返回 `错误页面_淘股吧`、访问太频繁或页面结构异常，batch 会熔断停止，不会把错误页当作详情成功入库。

主进程：

```bash
python main.py
```

复用最近一次报告发送测试消息：

```bash
python main.py testsend
```

实时抓取并立即发送：

```bash
python main.py testsend-live
```

## 输出

- `data/tgb-sample.sqlite`: TASK06 sample 小闭环数据库
- `data/tgb-incremental.sqlite`: TASK06 incremental 增量数据库
- `data/tgb-backfill-sample.sqlite`: TASK07 backfill sample 数据库
- `data/tgb-full-trial.sqlite`: TASK09 受控 full trial 数据库
- `output/`: 爬虫生成的 JSON、HTML，以及最终发送给渠道的 Markdown
- `output/latest_report.md`: 最近一次发送用的 Markdown
- `output/report-YYYYMMDD-HHMMSS.md`: 按时间归档的发送内容
- `logs/`: 主进程日志、PM2 日志
- `state/latest_report.json`: 最近一次完整报告
- `state/main_state.json`: 主进程每日执行状态

## 部署

`.env` 配好 `UPLOAD_HOST / UPLOAD_USER / UPLOAD_PASSWORD` 后执行：

```bash
python deploy.py
```

默认部署到：

```text
/home/nuonuo/app/taoguba-crawler-skill
```

## PM2

```bash
cd /home/nuonuo/app/taoguba-crawler-skill
pm2 start ecosystem.config.js
pm2 save
```
