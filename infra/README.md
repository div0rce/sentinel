# Sentinel infrastructure (Terraform)

Deployment target: AWS, `us-east-1`, **demo only**.

This directory provisions everything the M10 demo needs: a VPC, an ECS Fargate
cluster running the backend + frontend tasks, an RDS Postgres instance with the
`vector` extension enabled at migration time, ECR repositories for the two
images, SSM Parameter Store entries for the runtime secrets, and a tightly
scoped GitHub Actions OIDC role that the manual-dispatch CD workflow assumes.

> **Read the cost & security posture below before running `apply`. The default
> configuration is engineered for a teardown-after-screenshots demo, not a
> production deployment.**

---

## Cost & security posture (deliberate, demo-only)

### Public-subnet / no-NAT

The VPC has two `/24` public subnets and **no NAT Gateway**. ECS tasks live in
those public subnets and get assigned public IPs (`assign_public_ip = true`)
so they can reach ECR for image pulls and Anthropic / OpenAI for outbound API
calls.

This is chosen because a NAT Gateway is the largest avoidable line item in any
small AWS deployment (≈$32/month idle, plus ~$0.045/GB processed). For a demo
that gets `terraform destroy`'d after screenshots, the saving is meaningful and
the security tradeoffs are acceptable **with tight security groups** (below).

If you ever lift this past the demo: **add private subnets and a NAT Gateway**
(or VPC interface endpoints for ECR / SSM / CloudWatch) and move the ECS tasks
there. Track that as the first item in the production-readiness backlog.

### RDS is not publicly accessible

Hard invariant. `aws_db_instance.publicly_accessible = false` is wired in
`modules/rds/main.tf` and the `rds` security group ingress is keyed only to the
backend task SG (`modules/network/main.tf`). Even though RDS lives in the same
public subnets as the tasks, the security group prevents internet reach.

### Reachability graph (encoded in security groups)

```
internet ──→ alb_sg           (80, 443)
alb_sg   ──→ frontend_sg      (8080)      ALB → nginx
alb_sg   ──→ backend_sg       (8000)      ALB → FastAPI /health
frontend_sg ─→ backend_sg     (8000)      nginx /api proxy → FastAPI
backend_sg ──→ rds_sg         (5432)      FastAPI → Postgres
```

Egress is open on the task SGs (so containers can reach ECR / Anthropic /
OpenAI / CloudWatch). RDS has no egress.

### Public routing

The ALB default target group is the frontend service, so `/`, `/review`, and
`/dashboard` all serve the React SPA even on hard refreshes or shared links.
The deployed frontend is built with `VITE_API_BASE=/api`; nginx proxies only
`/api/*` to FastAPI and strips the `/api` prefix before forwarding. `/health`
is the only public path routed directly from the ALB to the backend target
group so backend health checks remain backend-specific.

### Single-AZ everywhere it matters

- RDS: `multi_az = false`, `db.t4g.micro`, 20 GB storage. Fine for the demo;
  unsuitable for production.
- ECS: `desired_count = 1` per service. A single task per service is the
  cheapest viable footprint; no auto-scaling.

### Backups, logs, deletion

- RDS: 1-day backup retention, `skip_final_snapshot = true`,
  `deletion_protection = false`. `terraform destroy` is therefore cheap and
  doesn't leave behind a final snapshot you'd forget to delete.
- CloudWatch Logs: `log_retention_days = 7` for the ECS task log groups.
- ECR: 7-day untagged-image expiry, 20-image cap.

---

## What this provisions (rough cost shape)

The numbers below are order-of-magnitude estimates against the AWS public price
list as of 2026-05; they exist to make "is this OK to leave running overnight?"
answerable without re-reading docs. **Use AWS's actual cost calculator for
binding numbers.**

| Resource              | Approx idle cost | Notes                                         |
| --------------------- | ---------------: | --------------------------------------------- |
| ALB                   |  ~$16/mo + LCU   | Cheapest line item that's still always-on.    |
| Fargate (2 tasks 0.25 vCPU / 0.5 GB) | ~$15/mo  | 24/7. Stop the services to stop the bill.     |
| RDS db.t4g.micro 20 GB |  ~$13/mo        | Single-AZ. ~$2/mo storage + ~$11/mo compute.  |
| ECR storage           |  <$1/mo          | 20-image cap on each repo.                    |
| Secrets / SSM         |   $0             | Standard parameters, not Advanced.            |
| CloudWatch Logs       |  <$1/mo          | 7-day retention; demo log volume is tiny.     |
| Data transfer         |  variable        | Outbound from ECS tasks → Anthropic/OpenAI.   |
| **Total idle floor**  | **~$45/mo**      | Plus per-second Fargate charges + traffic.    |

`terraform destroy` removes all of the above. Run it the moment screenshots
are captured.

---

## Apply / destroy recipe

### Pre-flight (one-time)

1. AWS account with IAM permissions to create the resources above.
2. AWS CLI configured (`aws configure` or equivalent — local profile, OIDC, or
   `AWS_PROFILE`).
3. A strong RDS master password. **Never commit it.** Pass via env:
   ```bash
   export TF_VAR_db_password="$(openssl rand -base64 24)"
   ```
4. A GitHub repo for the OIDC role's trust policy:
   ```bash
   export TF_VAR_github_repository="OWNER/sentinel"
   ```
   Leave unset to skip the OIDC role (manual deploys only).

### Validate without applying

```bash
cd infra/
terraform fmt -recursive -check
terraform init   # downloads providers; no AWS calls
terraform validate
```

`terraform fmt`, `init`, and `validate` make no AWS API calls.

### Apply (this is the cost moment)

```bash
terraform plan -out=plan.tfplan   # READ THIS BEFORE APPLY
terraform apply plan.tfplan
```

After apply succeeds:

```bash
terraform output ci_role_arn   # if github_repository was supplied
```

Add that ARN to the repo's `AWS_ROLE_ARN` secret (Settings → Secrets and
variables → Actions). The CD workflow assumes this role via OIDC.

### Write the runtime secrets out-of-band

```bash
aws ssm put-parameter --name /sentinel/anthropic_api_key \
  --type SecureString --value "$ANTHROPIC_API_KEY" --overwrite

aws ssm put-parameter --name /sentinel/openai_api_key \
  --type SecureString --value "$OPENAI_API_KEY" --overwrite
```

(`/sentinel/database_url` is composed by Terraform from the RDS outputs and
already populated.)

Then bounce the backend service so the new secret values are picked up:

```bash
aws ecs update-service \
  --cluster sentinel-cluster --service sentinel-backend \
  --force-new-deployment --no-cli-pager
```

### Run migrations + seed

The backend image runs migrations at task start? **No** — by design. Run them
once, manually, against the public ALB DNS using a one-off task or by exec'ing
into a running task. The simplest path for the demo: SSH-tunnel via a
short-lived Fargate task, run `alembic upgrade head` and `python -m
backend.app.ingest --path data/sample`. Recipe in `docs/demo.md` (M11).

### Deploy via CD

Manual dispatch only. From the GitHub UI: Actions → CD → Run workflow → choose
`backend` / `frontend` / `both`. Workflow:

1. Builds the requested images.
2. Pushes to ECR with the git SHA tag.
3. `aws ecs update-service --force-new-deployment` for each service.

### Destroy

```bash
terraform destroy
```

Removes everything provisioned by this configuration, including ECR images
(force_delete = true on the repos so destroy doesn't hang on lingering tags).

> **Tear down immediately after capturing screenshots.** Leaving the stack
> running overnight costs ~$1.50; leaving it for a month costs ~$45.

---

## What's not in this directory

- **No remote state.** Terraform state lives locally as `terraform.tfstate`.
  This is appropriate for a single-operator demo; for any second user, convert
  to an S3 backend + DynamoDB lock table first. Scope and recipe are out of
  M10.
- **No TLS certificate / Route 53.** The ALB serves plain HTTP on port 80. For
  a real demo, attach an ACM cert and add a 443 listener; the ALB SG already
  permits 443 ingress.
- **No CloudFront / WAF / observability beyond `/health` + structured logs.**
  Out of M10.
- **No auto-scaling rules.** `desired_count = 1` per service. Edit the
  `aws_ecs_service` blocks in `modules/ecs/main.tf` to change.

---

## Module map

```
infra/
├── versions.tf       provider pins (aws ~> 5.70, random ~> 3.6)
├── variables.tf      project_name, region, db creds, image tags, github_repository
├── main.tf           wires the modules
├── outputs.tf        ALB DNS, ECR URLs, ECS names, RDS endpoint, CI role ARN
└── modules/
    ├── network/      VPC, 2 public subnets, IGW, public RT, 4 SGs
    ├── ecr/          two repos with lifecycle policies
    ├── secrets/      SSM Parameter Store entries (API keys + DATABASE_URL)
    ├── rds/          Postgres 16.4 db.t4g.micro single-AZ, parameter group
    ├── ecs/          cluster, ALB + target groups + listener, task defs, services, log groups, IAM
    └── ci_oidc/      GitHub Actions OIDC provider + role (scoped to ECR push + ECS update-service)
```

---

## Validation in CI

The CI workflow does **not** run `terraform plan` or `apply`. It does run
`terraform fmt -check` and `terraform validate` against this directory in a
job that does not need AWS credentials, so a syntax or wiring regression is
caught on every PR. Plan/apply remain a manual operator action.
