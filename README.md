RDS performance comparision project
===================================

Initial goal of this repository is to compare performance of RDS on x86_64 to one on Graviton.

Other things that could be added:

* Collect versioning data and test results to some structured artifact.
* Collect monitoring data of a test driver VM to ensure it is not a bottleneck.
* Ability to tune the RDS with parameter groups so we can test with various PostgreSQL configurations.
* Currently we only run *TPC-C* benchmark, but we could add *TPC-H* (simulates a complex analytical and decision-support environment, representative of OLAP workloads common
in data warehousing scenarios) and *Vector Similarity Search* - see [Performance and Scale for Modern Database Workloads](https://www.purestorage.com/content/dam/pdf/en/white-papers/wp-performance-scale-for-modern-database-workloads.pdf) for test they used for similar purpose.

Setup your worstation
---------------------

To run the test we will need AWS CLI.
To install it follow the [guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html).
Now setup your credentials with this wizzard:

    aws configure

Also we will need Ansible and Python modules to work with AWS:

    dnf install -y ansible python3-botocore python3-boto3
    ansible-playbook doit.yaml


Run the test
------------

Default values for the experiment are in `inventory.ini` and you can override things you want to override on command line like showed below:

First create a EC2 VM that will run the test and RDS instance that will be tested:

    ansible-playbook -i inventory.ini playbooks/setup.yaml -e project_name=rds-perf-comparision -e owner_name=<login> -e aws_ec2_instance_type=t2.micro -e aws_ec2_ssh_key_name=<key_name> -e aws_ec2_ssh_private_key_file=~/.ssh/id_rsa -e aws_rds_instance_type=db.t3.micro

Then run the test:

    ansible-playbook -i inventory.ini playbooks/test.yaml -e ...

Then cleanup resurces created on AWS:

    ansible-playbook -i inventory.ini playbooks/cleanup.yaml -e ...

Note this is not complete and cleanup needs to be finished manually on AWS console by deleting VPC and all it's child resources.

Also you can run all of the playbooks in one go and store the output:

    mkdir -p results/
    ansible-playbook -i inventory.ini playbooks/setup.yaml playbooks/test.yaml playbooks/cleanup.yaml -e ... 2>&1 | tee results/run-$( date -Ins | sed 's/[^a-zA-Z0-9-]/_/g' )-db_t3_micro.log


Interpreting results
--------------------

Setup playbook output is this - it shows what resources were created in AWS and how to connect to them:

    TASK [Display connection information] *************************************
    ok: [localhost] => {
        "msg": [
            "Using these AWS entities:",
            "  VPC vpc-078f3a3ea3fda702f",
            "  subnet 1 subnet-0e57d25574801d6c1",
            "  subnet 2 subnet-08b877156641488d5",
            "  subnet group for RDS rds-perf-comparision-rds-subnet-group",
            "  route rtb-03e3c1973cfae9a76",
            "  gateway igw-01eda9eb9bccc86e2",
            "  securty group for VM sg-0935fdceb834d28ee",
            "  securty group for RDS sg-07b0b3bca0c6b7121",
            "EC2 Instance Public IP: 18.117.99.200",
            "  to connect to it: ssh -i ~/.ssh/id_rsa-fedora3 ec2-user@18.117.99.200",
            "RDS Endpoint: rdsperfcomparisionrds.cv5vurnttubm.us-east-2.rds.amazonaws.com",
            "  to connect to it (from VM): PGPASSWORD=... psql --host rdsperfcomparisionrds.cv5vurnttubm.us-east-2.rds.amazonaws.com --port 5432 --username myuser postgres"
        ]
    }

Currently the test runs "TPC-C" benchmark from HammerDB portfolio that stresses trasactional aspect of the database.

Most important test playbook output part is this:

    TASK [Show results] *******************************************************
    ok: [18.117.99.200] => {
        "msg": "RESULTS: NOPM = 7325, TPM = 17105"
    }

These two numbers have following meaning:

* **NOPM** stands for *new orders per minute* and determines how quickly is the test application doing it's work. This value is most important metric and if you would run the same test with same parameters agains't different DB engine (e.g. MySQL), you can compare these values to compare performance.
* **TPM** stands for *transactions per minute* and it is a metric specific for PostgreSQL engine.

For both of these metric holds "higher the better".
