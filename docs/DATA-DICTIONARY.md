# 饮用水批次质控定义

id保留前导零；batch+analyte+pair决定平行样配对。kind为sample、duplicate、spike、blank。浓度单位mg/L、ug/L统一为mg/L；数值用Decimal。检出限Pb、As均为0.001mg/L，限定值形式<0.001不按零处理。

均值低于5倍检出限时，平行样采用绝对差<=检出限；其余采用差值/均值<=20%。双零通过绝对差规则。加标回收=(加标样-本底)/加标量×100%，80—120%通过；加标量非正失败。空白严格超过检出限才判污染。

同id最高version为生效复测，同版本重复隔离。放行优先级为空白污染、空白缺失、回收失败、加标异常、配对失败、限定值复核。每个批次每项必须有空白；受限值进入人工复核。失败检测批生成逐样复测任务和下一最低版本。

复测采用batch+analyte+id作为身份键，在此身份内选择最高version；不同检测项允许复用同样品编号。

## 期间入账

入账CSV字段：id、batch、analyte、sampled（采样日期）、ran（上机日期，可空）、version。样品身份键为batch+analyte+id+version，在台账中唯一，每份样品只落到一个报告期。

归属期取采样日期所在月份，与上机日期无关。归属期开放则正常入账（POSTED）；归属期已封账则补记（SUPPLEMENT）至其后最近开放期，归属期作为证据保留，已封账报告不改写；无可用开放期则拒绝（NO_OPEN_PERIOD）。ran为空记待入账（PENDING/AWAITING_RUN），不阻塞封账，上机后按当时归属规则入账，身份行更新而非新增。

拒绝原因码：ID_REQUIRED、VERSION_INVALID、SAMPLED_REQUIRED、SAMPLED_INVALID、RAN_INVALID、RAN_BEFORE_SAMPLED、NO_OPEN_PERIOD。重复跳过原因码：IN_FILE（文件内重复）、ALREADY_POSTED（台账已入账）。待入账原因码：AWAITING_RUN。

封账要求期间开放、无未处置异常记录（归属该期且状态为拒绝）、revision匹配；三者任一失败则不生成新版报告，旧版报告保持有效。封账快照含入账明细、待上机清单与计数，摘要可复核。待上机样品随封账快照披露，后续迟到时补记至其后最近开放期。
