RDS performance comparision project
===================================

Initial goal of this repository is to compare performance of RDS on x86_64 to one on Graviton.

Sources I have used when working on this:

* Got a general overview of TPC-C test from [Database benchmarkin - an unexpected journey](https://www.pgday.ch/common/slides/2025_20250626_dkrautschick_SwissPGDay_BenchmarkJourney.pdf)
* Got a sense of various benchmarks from [Performance and Scale for Modern Database Workloads](https://www.purestorage.com/content/dam/pdf/en/white-papers/wp-performance-scale-for-modern-database-workloads.pdf)
* Got more info on how to run the test in an unatended manner from [Configuring HammerDB for Database Performance Benchmark via CLI](https://newbiedba.wordpress.com/2020/08/19/configuring-hammerdb-for-database-performance-benchmark-via-cli/)
* https://www.n0derunner.com/notes-on-tuning-postgres-for-memory-benchmarks/
* https://services.google.com/fh/files/misc/alloydb_omni_oltp_benchmarking_guide.pdf

Setup your workstation
----------------------

To run the test you need the AWS CLI. Install it using the [getting started guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html), then configure credentials:

    aws configure

Install Ansible and the Python modules used by the AWS collections (Fedora/RHEL example):

    dnf install -y ansible python3-botocore python3-boto3

Run all playbooks from the project root (`rds-perf-comparision`) so `ansible.cfg` and paths like `playbooks/../results` resolve correctly:

    cd rds-perf-comparision

Configuration
-------------

Defaults and AWS tags live in `inventory.ini` (`project_name`, `owner_name`, region, EC2/RDS sizes, SSH key, HammerDB settings, and so on). Override any variable with `-e name=value` on the command line.

Playbooks
---------

| Playbook | Purpose |
| -------- | ------- |
| `playbooks/setup.yaml` | Creates VPC, subnets, security groups, RDS (with parameter group), EC2 driver host, and adds the instance to group `new_ec2_instances`. Writes `setup-metadata-<stamp>.json` under the results directory. |
| `playbooks/test.yaml` | Runs HammerDB TPC-C on `new_ec2_instances` (Podman + HammerDB image). After the benchmark, the second play on `localhost` merges setup data and writes `run-metadata-<stamp>.json` for CloudWatch correlation. |
| `playbooks/fetch.yaml` | Reads run metadata, pulls RDS and EC2 CloudWatch statistics for the test window, and writes a combined metrics JSON (NOPM, TPM, plus `rds_cloudwatch` / `ec2_cloudwatch`). |
| `playbooks/cleanup.yaml` | Removes EC2, RDS, parameter group, subnet group, and VPC for the given `project_name` / `owner_name` tags. |
| `playbooks/run-matrix.yaml` | Loops over RDS instance classes, virtual-user counts, and repeat runs: for each cell it runs setup → test → fetch → copies artifacts into `results/archive/` → cleanup. Intended for full comparison matrices. |

**Important:** `setup.yaml` and `test.yaml` must run in the *same* `ansible-playbook` invocation when you create fresh infrastructure, so `add_host` from setup is visible to the test play. `fetch.yaml` should run in the same invocation as well, or you must pass `-e perf_run_stamp=...` matching the timestamp in `results/run-metadata-<stamp>.json` (otherwise `fetch` looks for unstamped `run-metadata.json`).

How to run
----------

### One-off run (single configuration)

Use values from `inventory.ini`, or override as needed (example shows common overrides):

1. Create infrastructure, run the benchmark, pull CloudWatch metrics, then tear down (recommended single chain):

       ansible-playbook -i inventory.ini \
         playbooks/setup.yaml playbooks/test.yaml playbooks/fetch.yaml playbooks/cleanup.yaml \
         -e project_name=rds-perf-comparision -e owner_name=<login> \
         -e aws_ec2_instance_type=m7i.12xlarge -e aws_ec2_ssh_key_name=<key_name> \
         -e aws_ec2_ssh_private_key_file=~/.ssh/<key>.pem \
         -e aws_rds_instance_type=db.m7g.xlarge

2. If you only want to run pieces manually, keep `setup.yaml` and `test.yaml` together. Run `fetch.yaml` immediately after in the same command, or with `-e perf_run_stamp=<same_stamp_as_metadata_files>`.

3. Cleanup must use the same `project_name` (and `owner_name`) used during setup:

       ansible-playbook -i inventory.ini playbooks/cleanup.yaml -e project_name=<same_as_setup>

Manual cleanup may still be needed in the AWS console if a play fails mid-way (orphaned VPC resources).

### Full matrix (many instance types × virtual users × repeats)

From the project root:

    ansible-playbook -i inventory.ini playbooks/run-matrix.yaml

Defaults in `run-matrix.yaml` include a list of RDS classes, `virtual_users_list`, and `run_count` (repeats per cell). Override examples:

    ansible-playbook -i inventory.ini playbooks/run-matrix.yaml \
      -e 'run_count=2' -e 'virtual_users_list=[8,16]'

To set which RDS instance types are iterated, pass a real YAML/Ansible list (the in-file default is easy to override incorrectly):

    ansible-playbook -i inventory.ini playbooks/run-matrix.yaml \
      -e 'instance_types_override=["db.m7i.xlarge","db.m7g.xlarge"]'

To write under a different top-level folder than `results/`:

    ansible-playbook -i inventory.ini playbooks/run-matrix.yaml -e matrix_results_subdir=my-results

That sets `results_dir` to `my-results/` under the project root; `archive` still lives at `my-results/archive/`.

Where results and logs are stored
---------------------------------

Unless you pass `-e perf_results_path=/absolute/or/relative/path`, all JSON artifacts go under:

    <project_root>/results/

(`project_root` is the parent of `playbooks/`.)

Files you will see there:

* **`setup-metadata-<perf_run_stamp>.json`** — EC2/RDS IDs, region, instance types (written by `setup.yaml`).
* **`run-metadata-<perf_run_stamp>.json`** — test window epochs, NOPM/TPM, virtual users, warehouses, plus IDs (written by `test.yaml` localhost play).
* **`vu_<vu>_wh_<warehouses>_<rds_class>_<ec2_type>_<perf_run_stamp>.json`** — benchmark headline numbers plus `rds_cloudwatch` and `ec2_cloudwatch` snapshots (written by `fetch.yaml`). Dots in instance types are replaced with underscores in the filename.

When using **`run-matrix.yaml`**, each matrix cell also gets:

* **`results/rds-perf-<sanitized_instance_type>-vu<N>-run<R>/`** — per-cell working directory.
* **`run-<RUN_TS>-vu<VU>-<instance_type_safe><R>.log`** inside that directory — full `ansible-playbook` stdout/stderr for setup+test+fetch+cleanup for that cell (`tee` from the matrix shell task).

The **`results/archive/`** folder
---------------------------------

Under `results/archive/` (or `<matrix_results_subdir>/archive/` if you customized the matrix output tree), the matrix playbook creates **one timestamped subdirectory per completed cell run**, named like:

    rds-perf-<sanitized_rds_class>-vu<N>-run<R>-<RUN_TS>/

Each archive directory holds a **snapshot of that run’s artifacts**: `run-metadata-*.json`, `setup-metadata-*.json`, the final `vu_*_...json` metrics file, and the same console log as in the per-cell folder. **Treat `archive/` as the long-term store of previous test results** from matrix runs; the top-level `results/` directory may also contain the latest metadata and metrics files from the most recent fetch.

Interpreting results
--------------------

Setup playbook output lists created AWS resources and how to connect. Example:

    TASK [Display connection information] *************************************
    ok: [localhost] => {
        "msg": [
            "Using these AWS entities:",
            "  VPC vpc-078f3a3ea3fda702f",
            ...
            "EC2 Instance Public IP: 18.117.99.200 (instance type: m7i.12xlarge)",
            "RDS Endpoint: ... (instance type: db.m7g.xlarge)",
            ...
        ]
    }

The test runs the TPC-C workload from HammerDB against PostgreSQL.

Typical test output:

    TASK [Show results] *******************************************************
    ok: [<ec2-ip>] => {
        "msg": "RESULTS: NOPM = 7325, TPM = 17105"
    }

Meaning of the headline metrics:

* **NOPM** (*new orders per minute*) — primary application throughput; use it to compare runs or engines when the workload is the same.
* **TPM** (*transactions per minute*) — PostgreSQL-specific transaction count from HammerDB.

Higher is better for both. The JSON from `fetch.yaml` adds CloudWatch context for RDS and the load-generator EC2 instance for the same time window.
