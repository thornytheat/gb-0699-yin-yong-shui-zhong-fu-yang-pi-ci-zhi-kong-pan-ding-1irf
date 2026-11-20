# 接口

`POST /api/run`：{"text":"CSV内容"}。同规则版本与输入摘要只产生一条批次。

`GET/POST /api/1` 至 `/api/7`：独立样例或自定义文件计算。各模块返回 report、quarantine、balance。

`POST /api/review`：id、整数revision、decision取通过或退回。旧版本409；阻断项不能通过。

`POST /api/8`：{"text":"入账CSV"}。同内容重跑返回同一批次且 `replayed=true`，不新增入账记录。`GET /api/8` 返回期间台账总览；`GET /api/8/sample` 返回样例；`GET /api/8/runs/{id}` 读取入账批次明细。

`POST /api/8/periods/{period}/seal`：{"revision":整数}。期间不存在404；已封账、存在未处置异常记录、revision陈旧均409，失败不生成新版报告。`GET /api/8/periods/{period}/report` 读取当前月报（开放期为草稿，封账期为快照）。

`GET /api/8/export/{id}`：入账证据CSV，逐样品含归属依据与未入账原因。`GET /api/8/periods/{period}/export`：月报CSV。

`GET /api/export/{id}`：唯一证据CSV。`GET /health`：存活检查。

错误：结构/数值422，版本冲突409，不存在404，文件过大413。逐行异常进入quarantine。
