## HBASE列族不能太多的真相

HRegionServer内部管理了一系列HRegion对象，每个HRegion对 应了table中的一个region，HRegion中由多 个HStore组成。每个HStore对应了Table中的一个column family的存储，可以看出每个columnfamily其实就是一个集中的存储单元，因此最好将具备共同IO特性的column放在一个column family中，这样最高效。

HStore存储是HBase存储的核心，由两部分组成，一部分是MemStore，一 部分是StoreFile。MemStore是 Sorted Memory Buffer，用户写入的数据首先会放入MemStore，当MemStore满了以后会Flush成一个StoreFile（底层实现是HFile）。

进行split的条件：该regiion下所有的storeFile中最大的storeFile大小超过阀值即进行split
在文件层次上，不同的列族，存储在不同的文件中。但是不同的列族，可能会共享一个region。

~~~shell
/hbase/zz/3917ebd872c0adcb9d6c5a9cfd30b87f/a

/hbase/zz/3917ebd872c0adcb9d6c5a9cfd30b87f/a/9210131397650425238
/hbase/zz/3917ebd872c0adcb9d6c5a9cfd30b87f/b
/hbase/zz/3917ebd872c0adcb9d6c5a9cfd30b87f/b/7083844554431109536
~~~

如上所示：两个不同的列族，共享了同一个region(3917ebd872c0adcb9d6c5a9cfd30b87f)。

由于不同的列族会共享region，所以有可能出现，一个列族已经有1000万行，而另外一个才100行。当一个要求region分割的时候，会导致100行的列会同样分布到多个region中。
这样就出现了基数问题。（如果表存在多个列族，列族A有100万行，列族B有10亿行，那么列族A可能会被分散到很多个Region上，这会导致扫描列族A的性能低下）

(某个column family在flush的时候，它邻近的column family也会因关联效应被触发flush，最终导致系统产生更多的I/O)
所以，一般建议不要设置多个列族。
