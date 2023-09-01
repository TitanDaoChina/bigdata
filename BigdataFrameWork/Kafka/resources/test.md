调用API
## 会员回购分析
- 接口地址： /api/memberRepoAnalysis
- 接口备注：回购会员消费力分布
- Content-Type：application/x-www-form-urlencoded
- 请求参数：

| 参数名称 | 参数类型 |             参数说明             |
| :----: | :----: |:----------------------------:|
|merchant_num|bigint|             店铺编号             |
|time_begin|date|    统计开始时间（格式：2022-12-01）     |
|time_end|date|     统计结束时间（格式：2022-12-31）      |
|retained_begin|date| 存量老客会员的计算开始时间（格式：2022-01-01） |
|retained_end|date| 存量老客会员的计算结束时间（格式：2022-01-31） |

- 返回格式，样例：
{"data":[{"member_old_buy_num":2779,"member_new_orders":15666,"member_new_buy_num":11121,"member_old_payment":9054265.53,"member_old_orders":3439,"member_orders":19105,"member_new_payment":38075386.2182,"member_buy_num":13900,"member_payment":47129651.7482}],"success":true}