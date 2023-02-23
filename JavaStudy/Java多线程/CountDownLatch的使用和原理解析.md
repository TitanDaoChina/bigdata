## 1、CountDownLatch 概念
CountDownLatch可以使一个获多个线程等待其他线程各自执行完毕后再执行。



CountDownLatch 定义了一个计数器，和一个阻塞队列， 当计数器的值递减为0之前，阻塞队列里面的线程处于挂起状态，当计数器递减到0时会唤醒阻塞队列所有线程，这里的计数器是一个标志，可以表示一个任务一个线程，也可以表示一个倒计时器，CountDownLatch可以解决那些一个或者多个线程在执行之前必须依赖于某些必要的前提业务先执行的场景。

## 2、CountDownLatch 常用方法说明
~~~
CountDownLatch(int count); //构造方法，创建一个值为count 的计数器。
await();//阻塞当前线程，将当前线程加入阻塞队列。
await(long timeout, TimeUnit unit);//在timeout的时间之内阻塞当前线程,时间一过则当前线程可以执行，
countDown();//对计数器进行递减1操作，当计数器递减至0时，当前线程会去唤醒阻塞队列里的所有线程。
~~~
## 3、用CountDownLatch 来优化我们的报表统计

功能现状

运营系统有统计报表、业务为统计每日的用户新增数量、订单数量、商品的总销量、总销售额......等多项指标统一展示出来，因为数据量比较大，统计指标涉及到的业务范围也比较多，所以这个统计报表的页面一直加载很慢，所以需要对统计报表这块性能需进行优化。



问题分析

统计报表页面涉及到的统计指标数据比较多，每个指标需要单独的去查询统计数据库数据，单个指标只要几秒钟，但是页面的指标有10多个，所以整体下来页面渲染需要将近一分钟。



解决方案

任务时间长是因为统计指标多，而且指标是串行的方式去进行统计的，我们只需要考虑把这些指标从串行化的执行方式改成并行的执行方式，那么整个页面的时间的渲染时间就会大大的缩短， 如何让多个线程同步的执行任务，我们这里考虑使用多线程，每个查询任务单独创建一个线程去执行，这样每个统计指标就可以并行的处理了。



要求

因为主线程需要每个线程的统计结果进行聚合，然后返回给前端渲染，所以这里需要提供一种机制让主线程等所有的子线程都执行完之后再对每个线程统计的指标进行聚合。 这里我们使用CountDownLatch 来完成此功能。





### 模拟代码

~~~
package com.enbrands.analyze.spark.metrics;

import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.enbrands.analyze.AbsJob;
import com.enbrands.dao.entity.DataReport;
import com.enbrands.dao.entity.TDgUserTag;
import com.enbrands.dao.mapper.DataReportMapper;
import com.enbrands.dao.mapper.TDgUserTagMapper;
import com.enbrands.shark.common.Context;
import com.enbrands.shark.common.datasource.ConnectionFactory;
import com.enbrands.shark.common.enums.AlertLevel;
import com.enbrands.shark.common.util.DingUtils;
import com.enbrands.shark.common.util.PropertiesUtil;
import com.enbrands.shark.common.util.ProxyDorisStreamLoad;
import com.enbrands.shark.common.util.TimeUtil;
import com.google.common.util.concurrent.ThreadFactoryBuilder;
import org.apache.commons.lang3.StringUtils;
import org.apache.doris.flink.cfg.DorisExecutionOptions;
import org.apache.doris.flink.table.DorisStreamLoad;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.joda.time.LocalDate;
import java.io.IOException;
import java.sql.SQLException;
import java.util.*;
import java.util.concurrent.*;
import java.util.stream.IntStream;

/**
 * @author YJF
 */
public class MetricsManager extends AbsJob {
    protected final List<Map<String, String>> metricsList = new ArrayList<>();
    protected String updateDay;
    protected String nowDay;
    private DorisExecutionOptions executionOptions;
    private DorisStreamLoad dorisStreamLoad;
    protected DorisStreamLoad dorisJobStreamLoad;
    protected transient ThreadPoolExecutor threadPoolExecutor;
    private static final ThreadFactory THREAD_FACTORY = new ThreadFactoryBuilder().setNameFormat("Process_task_%d").build();
    protected DataReportMapper dataReportMapper;
    protected TDgUserTagMapper tDgUserTagMapper;
    protected CountDownLatch latch;
    protected String reportApi;
    protected KafkaProducer<Integer, Integer> kafkaProducer;

    public static void main(String[] args) {
        new MetricsManager(args).run();
    }

    public MetricsManager(String[] args) {
        super(args);
    }

    @Override
    public void setup() {
        updateDay = TimeUtil.dayStrToHiveDay(time);
        nowDay = TimeUtil.plusDays(new LocalDate().toString(), -1);
        executionOptions = DorisExecutionOptions.defaults();
        threadPoolExecutor = new ThreadPoolExecutor(5, 10, 10, TimeUnit.SECONDS, new LinkedBlockingDeque<>(), THREAD_FACTORY, new ThreadPoolExecutor.CallerRunsPolicy());
        ConnectionFactory connectionFactory = new ConnectionFactory("cos_jdbc.properties");
        dataReportMapper = connectionFactory.getMapper(DataReportMapper.class);
        tDgUserTagMapper = connectionFactory.getMapper(TDgUserTagMapper.class);
        dorisStreamLoad = new ProxyDorisStreamLoad("ads_metrics_result", executionOptions).getDorisStreamLoad();
        dorisJobStreamLoad = new ProxyDorisStreamLoad("ads_metrics_crowd_report", executionOptions).getDorisStreamLoad();
        reportApi = PropertiesUtil.getValue("report.api");
        //创建kafka producer
        Properties props = new Properties();
        props.setProperty(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, PropertiesUtil.getValue("report.kafka"));
        props.put("key.serializer", "org.apache.kafka.common.serialization.StringSerializer");
        props.put("value.serializer", "org.apache.kafka.common.serialization.StringSerializer");
        kafkaProducer = new KafkaProducer<>(props);
    }

    @Override
    public void handle() {
        try {
            //判断是否需要生成tag表数据
            generateTag();

            //1、定时--指标体系任务
            SqlGenerate sqlGenerate = new SqlGenerate();
            String[] split = metrics.split(",");
            List<Integer> metricList = new ArrayList<>();
            for (String s : split) {
                metricList.add(Integer.valueOf(s));
            }
            Map<Integer, List<String>> metricsSql = sqlGenerate.getMetricsSql(merchant, updateDay, metricList);
            latch = new CountDownLatch(metricsSql.get(0).size());
            // 执行派生指标SQL
            sqlExecute(metricsSql.get(0), latch, dorisStreamLoad, updateDay);
            latch.await();
            // 扫尾
            flushToDoris(metricsList, dorisStreamLoad);
            // 执行复合指标SQL
            latch = new CountDownLatch(metricsSql.get(1).size());
            sqlExecute(metricsSql.get(1), latch, dorisStreamLoad, updateDay);
            latch.await();
            flushToDoris(metricsList, dorisStreamLoad);

            //2、定时--自助报表任务
            if (updateDay.equals(nowDay)) {
                QueryWrapper<DataReport> wrapper = new QueryWrapper<>();
                wrapper.lambda().in(DataReport::getStatus, 2);
                List<DataReport> dataReportList = dataReportMapper.selectList(wrapper);

                for (DataReport job : dataReportList) {
                    String updateTime = job.getDataUpdateTime().substring(0, 10);
                    while (!TimeUtil.isAfter(updateTime, nowDay)) {

                        dataReportProcess(job, sqlGenerate, updateTime);
                        updateTime = TimeUtil.plusDays(updateTime, 1);
                        job.setDataUpdateTime(TimeUtil.prettyFormat(System.currentTimeMillis(), Context.TIME_ZONE));
                        dataReportMapper.updateById(job);

                        //报表自动更新文件
                        ProducerRecord producerRecord = new ProducerRecord<String, String>(PropertiesUtil.getValue("report.topic"), job.getId().toString());
                        kafkaProducer.send(producerRecord);

                    }
                }
            }

            //3、定时--指标体系人数详情任务
            sqlInsertExecute(metricsSql.get(2));
        } catch (Throwable e) {
            Thread.currentThread().interrupt();
            logger.error("MetricsManager occur error for:", e);
            DingUtils.send("指标体系任务失败告警", e, AlertLevel.P2);
        }
    }

    /**
     * 自助报表数据计算
     *
     * @param dataReport  自助报表
     * @param sqlGenerate sql生成类
     * @param updateDay   计算时间
     */
    protected void dataReportProcess(DataReport dataReport, SqlGenerate sqlGenerate, String updateDay) throws Throwable {
        List<Integer> ids = JSONObject.parseArray(dataReport.getKpiList()).toJavaList(Integer.class);
        String crowdJson = dataReport.getCrowdId();
        if (StringUtils.isEmpty(crowdJson)) {
            return;
        }
        JSONArray crowdIdArray = JSONObject.parseArray(crowdJson);
        StringJoiner joiner = new StringJoiner(",");
        IntStream.range(0, crowdIdArray.size()).mapToObj(i -> crowdIdArray.getJSONObject(i).getString("crowdId")).forEachOrdered(joiner::add);
        String crowdId = joiner.toString();
        Map<Integer, List<String>> metricsDataReportSql = sqlGenerate.getMetricsSql(dataReport.getMerchantNum(), updateDay, ids, crowdId);
        // 执行派生指标SQL
        latch = new CountDownLatch(metricsDataReportSql.get(0).size());
        sqlExecute(dataReport.getId(), metricsDataReportSql.get(0), latch, dorisJobStreamLoad, updateDay, DATA_REPORT_JOB_TYPE);
        latch.await();
        // 扫尾
        flushToDoris(metricsList, dorisJobStreamLoad);
        // 执行复合指标SQL
        latch = new CountDownLatch(metricsDataReportSql.get(1).size());
        sqlExecute(dataReport.getId(), metricsDataReportSql.get(1), latch, dorisJobStreamLoad, updateDay, DATA_REPORT_JOB_TYPE);
        latch.await();
        flushToDoris(metricsList, dorisJobStreamLoad);
    }

    /**
     * 用户标签计算
     *
     * @param userTags 配置数据List
     */
    protected void clcUserTag(List<TDgUserTag> userTags, String clcDay) throws SQLException {
        int index = 4;
        for (int i = 5; i < userTags.size(); i++) {
            String[] regexStr = getRegexStr(userTags, clcDay);
            TDgUserTag tUserTag = userTags.get(i);
            String dim = tUserTag.getDim();
            String userTagField = tUserTag.getUserTagField();
            if (tUserTag.getUserTagName().contains("会员")) {
                regexStr[3] = "member_id";
            }
            //表结构主键ID严格相关
            if (tUserTag.getId() == 9) {
                regexStr[4] = "is_member";
            }
            String[] dims = dim.split(",", -1);
            String[] fields = userTagField.split(",", -1);
            for (String field : fields) {
                for (String dimType : dims) {
                    index++;
                    regexStr[index] = field + "_" + dimType;
                }
            }

            //处理掉tag表sql生成中的member_id字段
            String res = "";
            for (int m = 0; m < regexStr.length; m++) {
                if(m == 3){
                    continue;
                }else if(m != regexStr.length - 1){
                    res += regexStr[m] + ",";
                }else {
                    res += regexStr[m] ;
                }
            }

            String sql = tUserTag.getSql().replace("${regex_str}", res).replace("${merchant_num}", merchant)
                    .replace("${update_at}", clcDay);
            for (String dimType : dims) {
                String startAt = TimeUtil.getStartDay(dimType, clcDay);
                sql = sql.replace("${start_at" + "_" + dimType + "}", startAt);
            }
            String finalSql = sql;
            MetricsResult.executeSql(finalSql);
        }
    }

    /**
     * 根据配置表中的字段构造用户标签表的插入字段
     *
     * @param userTags 配置数据
     * @return 用户标签表的插入字段
     */
    private String[] getRegexStr(List<TDgUserTag> userTags, String clcDay) {
        int regexSzie = 0;
        for (TDgUserTag userTag : userTags) {
            if (StringUtils.isEmpty(userTag.getDim())) {
                regexSzie++;
            } else {
                String[] dim = userTag.getDim().split(",", -1);
                String[] field = userTag.getUserTagField().split(",", -1);
                regexSzie += dim.length * field.length;
            }
        }
        String[] regexStr = new String[regexSzie];
        regexStr[0] = "merchant_num";
        regexStr[1] = "ouid";
        regexStr[2] = "'" + clcDay + "'";

        return regexStr;
    }

    @Override
    public void cleanup() {
        kafkaProducer.close();
        try {
            if (threadPoolExecutor != null) {
                threadPoolExecutor.shutdown();
                if (!threadPoolExecutor.awaitTermination(10, TimeUnit.HOURS)) {
                    logger.warn("Failed to close executor in 10 hours");
                }
            }
        } catch (Exception e) {
            logger.error("Close thread pool occur error ", e);
            Thread.currentThread().interrupt();
        } finally {
            try {
                this.dorisStreamLoad.close();
                this.dorisJobStreamLoad.close();
            } catch (IOException e) {
                logger.error("Close dorisStreamLoad error ", e);
            }
        }
    }

    private void sqlExecute(List<String> sqlLists, CountDownLatch countDownLatch, DorisStreamLoad dorisLoad, String updateDay) {
        sqlLists.forEach(sql -> threadPoolExecutor.execute(() -> {
            List<Map<String, String>> resultList;
            try {
                resultList = MetricsResult.executeSql(sql, updateDay);
                for (Map<String, String> stringMap : resultList) {
                    writeRecord(stringMap, dorisLoad);
                }
            } catch (Exception e) {
                logger.error("SQL execute with sql={},updateDay={} failed for: ", sql, updateDay, e);
                DingUtils.send(e.getMessage(), e,AlertLevel.P2);
            }

            if (countDownLatch != null) {
                countDownLatch.countDown();
            }
        }));
    }

    protected void sqlExecute(Integer jobId, List<String> sqlLists, CountDownLatch countDownLatch, DorisStreamLoad dorisLoad, String updateDay, String jobType) {
        sqlLists.forEach(sql -> threadPoolExecutor.execute(() -> {
            //自助报表-1、后链路-2
            List<Map<String, String>> resultList;
            try {
                resultList = MetricsResult.executeCrowdSql(jobId, sql, updateDay, jobType);
                for (Map<String, String> stringMap : resultList) {
                    writeRecord(stringMap, dorisLoad);
                }
            } catch (Exception e) {
                logger.error("SQL execute with jobId={},sql={},updateDay={},jobType={} failed for: ", jobId, sql, updateDay, jobType, e);
                DingUtils.send(e.getMessage(), e,AlertLevel.P2);
            }

            if (countDownLatch != null) {
                countDownLatch.countDown();
            }
        }));
    }

    private void sqlInsertExecute(List<String> sqlLists) throws SQLException {
        String deleteSql = String.format("delete from ads.ads_metrics_crowd_detail where update_day = '%s'", updateDay);
        MetricsResult.executeSql(deleteSql);
        for (String sql : sqlLists) {
            MetricsResult.executeSql(sql);
        }
    }

    /**
     * 判断是否生成tag表数据
     * @throws SQLException
     */
    protected void generateTag() throws SQLException {
        int num =  MetricsResult.executeQuerySql(merchant, updateDay);
        //通过判断tag表历史数据来判断是否需要执行当天数据
        if (merchant.split(",").length != num) {
            //用户标签
            List<TDgUserTag> userTags = tDgUserTagMapper.queryTemplate();
            clcUserTag(userTags, updateDay);
        }
    }

    /**
     * 数据存入Doris
     *
     * @param row 单条数据
     * @throws IOException IO异常
     */
    private synchronized void writeRecord(Map<String, String> row, DorisStreamLoad dorisStreamLoad) throws IOException {
        metricsList.add(row);
        if (this.executionOptions.getBatchSize() > 0 && metricsList.size() >= this.executionOptions.getBatchSize()) {
            flushToDoris(metricsList, dorisStreamLoad);
        }
    }
}

~~~



