# Sample data (synthetic)

`contracts_sample.csv` is **synthetic**. Every vendor, department, contract and amount in it is invented
by `scripts/make_sample_data.py`. It uses the real column names of the Government of Canada
*Contracts over $10,000* open dataset so the pipeline, tests and CI run offline.

For real analysis, load the public dataset instead:

```bash
procurement-agent ingest-data          # downloads the full open dataset (several hundred MB)
```

The real data is published by the Treasury Board of Canada Secretariat on the Open Government Portal
under the Open Government Licence – Canada.
