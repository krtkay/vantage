# Professional deployment on AWS

Reference guide (not provisioned here). Two paths, simplest first. Both assume the
[`Dockerfile`](../Dockerfile) and an AWS account with the AWS CLI configured.

- **A. App Runner** — least ops; point it at an image and it runs + autoscales + gives HTTPS.
- **B. ECS Fargate + ALB** — more control (VPC, scaling policies, multiple services).

Secrets (the LLM key) go in **AWS Secrets Manager** in both — never in the image.

---

## 0. Build and push the image to ECR (shared by both paths)

```bash
AWS_REGION=ap-south-1
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REPO=vantage
ECR=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

aws ecr create-repository --repository-name $REPO --region $AWS_REGION

aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $ECR

docker build -t $REPO .
docker tag $REPO:latest $ECR/$REPO:latest
docker push $ECR/$REPO:latest
```

## 1. Store the API key in Secrets Manager

```bash
aws secretsmanager create-secret \
  --name vantage/groq \
  --secret-string '{"GROQ_API_KEY":"your_key_here"}' \
  --region $AWS_REGION
```

---

## A. AWS App Runner (recommended for simplicity)

1. **App Runner → Create service → Container registry → Amazon ECR**, choose the
   image you pushed.
2. **Port:** `8501`. **Start command:** inherited from the Dockerfile `CMD`.
3. **Environment / secrets:** map `GROQ_API_KEY` from the Secrets Manager secret,
   set `LLM_PROVIDER=groq`.
4. **Health check path:** `/_stcore/health`.
5. Create — App Runner builds, deploys, autoscales, and returns an HTTPS URL.

Grant the service's instance role permission to read the secret
(`secretsmanager:GetSecretValue` on that ARN).

---

## B. ECS Fargate + Application Load Balancer

High level:

1. **ECS cluster** (Fargate).
2. **Task definition**: image = your ECR URI; container port `8501`; inject
   `GROQ_API_KEY` from Secrets Manager via the task's `secrets` block; task role
   with `secretsmanager:GetSecretValue`.
3. **Service** behind an **ALB**; target group health check `/_stcore/health`;
   desired count ≥ 1; autoscaling on CPU.
4. **Security groups**: ALB open on 443/80; tasks accept 8501 only from the ALB.
5. **HTTPS**: ACM certificate on the ALB listener; point your domain (Route 53) at
   the ALB.

> Data: the image bakes in the SQLite DB, so no database service is needed. If you
> move to a managed warehouse (RDS Postgres / Redshift), set `DATABASE_URL` as an
> env var — the agent introspects it with no code change. Use a **read-only** DB
> user.

---

## Continuous deployment (GitHub Actions → ECR → redeploy)

Add a deploy job (runs after the CI in `.github/workflows/ci.yml`). Configure AWS
credentials via GitHub OIDC (preferred) or repo secrets.

```yaml
deploy:
  needs: lint-and-test
  if: github.ref == 'refs/heads/main'
  runs-on: ubuntu-latest
  permissions:
    id-token: write
    contents: read
  steps:
    - uses: actions/checkout@v4
    - uses: aws-actions/configure-aws-credentials@v4
      with:
        role-to-assume: arn:aws:iam::<ACCOUNT_ID>:role/<github-oidc-role>
        aws-region: ap-south-1
    - uses: aws-actions/amazon-ecr-login@v2
      id: ecr
    - name: Build & push
      run: |
        IMAGE=${{ steps.ecr.outputs.registry }}/vantage:${{ github.sha }}
        docker build -t "$IMAGE" .
        docker push "$IMAGE"
    # App Runner: trigger a new deployment (auto-deploy can also be enabled on the service)
    - run: aws apprunner start-deployment --service-arn <SERVICE_ARN>
    # ECS alternative:
    # - run: aws ecs update-service --cluster <c> --service <s> --force-new-deployment
```

---

## Cost & hardening notes

- **App Runner / Fargate** bill per vCPU-hour + memory; a single small task is a
  few dollars/month at idle-ish usage. Scale to zero isn't native on Fargate; App
  Runner can pause.
- Keep the **LLM key in Secrets Manager**, rotate it, and scope the task/instance
  role to just that secret ARN.
- Run the DB connection **read-only** (already enforced in-app) and give any real
  warehouse user `SELECT`-only grants.
- Put **CloudWatch Logs** on the service; the app already emits structured JSON
  logs, so they're queryable in CloudWatch Logs Insights.
- Consider **Langfuse** (set `LANGFUSE_*` env) for LLM-level tracing and cost
  dashboards.
