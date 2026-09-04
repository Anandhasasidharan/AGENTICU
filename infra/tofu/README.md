# AgentICU on AWS (OpenTofu)

Production stack: **ECS Fargate** (AgentICU API + Grafana) + **RDS Postgres**,
fronted by one ALB (`:80` → API, `:8080` → Grafana). Uses the account default
VPC to avoid NAT costs. Local dev stays on `docker-compose.yml`.

## Prerequisites

- [OpenTofu](https://opentofu.org/docs/intro/install/) >= 1.6
- AWS CLI with credentials (`aws sts get-caller-identity` works)
- Docker (to build/push the API image)

## 1. State bucket (once)

```bash
aws s3api create-bucket --bucket agenticu-tofu-state --region us-east-1
aws s3api put-bucket-encryption --bucket agenticu-tofu-state \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

The backend block in `versions.tf` already enables native state locking
(`use_lockfile = true`) — no DynamoDB table needed.

## 2. Build & push the API image

```bash
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin <ACCOUNT>.dkr.ecr.us-east-1.amazonaws.com

# ECR repo is created by tofu; for the very first push create it once:
aws ecr create-repository --repository-name agenticu --region us-east-1

docker build -t agenticu:latest ../..
docker tag agenticu:latest <ACCOUNT>.dkr.ecr.us-east-1.amazonaws.com/agenticu:latest
docker push <ACCOUNT>.dkr.ecr.us-east-1.amazonaws.com/agenticu:latest
```

## 3. Deploy

```bash
cd infra/tofu
tofu init
tofu plan -var="container_image=<ACCOUNT>.dkr.ecr.us-east-1.amazonaws.com/agenticu:latest" \
           -var="api_key=<your-key>" -out=tfplan
tofu apply tfplan
```

## 4. Migrate the database

RDS has no initdb hook, so apply `schema.sql` once via the CLI from your machine
(security group allows only ECS traffic by default — run from a host with access
or temporarily allow your IP on port 5432):

```bash
AGENTICU__STORAGE__DSN="postgresql://agenticu:<password>@<rds-endpoint>:5432/agenticu" \
  agenticu migrate --dsn "postgresql://agenticu:<password>@<rds-endpoint>:5432/agenticu"
```

Get `<password>` from Secrets Manager (`agenticu/db-password`) and
`<rds-endpoint>` from `tofu output rds_endpoint`.

Note: the ECS task receives the DB password via the `AGENTICU__DB_PASSWORD`
secret. If your `TraceStore` DSN handling needs the password inline, update the
task definition env to build the DSN from the secret (or extend the app to read
it).

## 5. Point the TUI at prod

```bash
agenticu tui --server "$(tofu output -raw api_url)" --api-key "<your-key>"
```

## 6. Grafana dashboard

The ECS Grafana starts empty (no EFS mount). Import
`src/agenticu/dashboard/grafana_dashboard.json` once via
`<grafana-url>/dashboard/import` (`tofu output -raw grafana_url`).

## Teardown

```bash
tofu destroy -var="container_image=<same-as-apply>" -var="api_key=<same>"
```

## Cost notes (rough, us-east-1)

- `db.t4g.micro` + 20 GB gp3: ~$15/mo · Fargate 2× (0.5 vCPU/1 GB): ~$30/mo
- ALB: ~$16/mo + LCU · ECR: ~$1/mo · Secrets/Logs: ~$1/mo
- Start with `desired_count = 1`; scale when needed.
