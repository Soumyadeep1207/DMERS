# DMERS AWS deployment

This deployment is separate from the local `docker-compose.yml`. Terraform provisions Amazon ECS on Fargate for the React frontend and Flask API, Amazon ECR for the images, an Application Load Balancer, private Amazon RDS for PostgreSQL, Secrets Manager, and CloudWatch logs. The existing local Docker workflow is unchanged.

The ALB sends `/api/*` requests to Flask and all other paths to the static frontend. RDS is private and only accepts PostgreSQL connections from the ECS task security group. The running API uses a restricted `dmers_app` database role. The RDS master credentials are only used by the one-off Fargate bootstrap task. The Review II database remains separate as `dmers_course` on the same RDS instance; the bootstrap task creates and seeds it without resetting existing tables. Production PostgreSQL setup does not create the known local demo passwords; Terraform creates a random first admin password in Secrets Manager.

## Requirements

- An AWS account with permissions to create VPC, ECS, ECR, RDS, IAM, Secrets Manager, CloudWatch, and load-balancer resources.
- AWS CLI v2, Docker Desktop, and Terraform 1.6 or later installed and authenticated (`aws configure` or an AWS IAM Identity Center profile).
- The project checked out locally. Run these commands from the project root in PowerShell.

Review current AWS charges before deployment. Fargate tasks, an ALB, RDS, ECR storage, and CloudWatch logs incur charges. This demo creates a single-AZ database and one task per service by default. Its ECS tasks have public IP addresses for outbound AWS/image access, but their security group accepts inbound traffic only from the ALB. RDS has no public access. Add a NAT gateway or VPC endpoints and remove task public IPs for a stricter production network.

## Deploy

### 1. Authenticate and create the ECR repositories

```powershell
aws sts get-caller-identity
Set-Location .\aws
terraform init
terraform apply -target=aws_ecr_repository.backend -target=aws_ecr_repository.frontend -target=aws_ecr_repository.bootstrap
```

The targeted first apply creates only the three image repositories. Terraform state contains generated database and application secrets after the full apply; keep `aws/terraform.tfstate*` private and never commit it. For team use, configure an encrypted, access-controlled remote Terraform backend before applying.

### 2. Build and push the images

Return to the project root, read the ECR account and registry host, then authenticate. Replace `<account-id>` with the account ID from `aws sts get-caller-identity`; `aws_region` defaults to `ap-south-1`.

```powershell
Set-Location ..
$Region = "ap-south-1"
$AccountId = (aws sts get-caller-identity --query Account --output text).Trim()
$Registry = "$AccountId.dkr.ecr.$Region.amazonaws.com"
aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $Registry

docker build --target production -t "$Registry/dmers-backend:latest" .\backend
docker build --target aws -t "$Registry/dmers-frontend:latest" .\frontend
docker build -f .\aws\bootstrap-course-db.Dockerfile -t "$Registry/dmers-course-bootstrap:latest" .

docker push "$Registry/dmers-backend:latest"
docker push "$Registry/dmers-frontend:latest"
docker push "$Registry/dmers-course-bootstrap:latest"
```

### 3. Provision the AWS services

```powershell
Set-Location .\aws
terraform apply
```

Terraform creates RDS and ECS together. The backend will report unhealthy until the separate Review II database is initialized in the next step. ECS keeps the containers running while the target group waits for a healthy response.

### 4. Initialize the coursework database once

```powershell
$Cluster = terraform output -raw ecs_cluster_name
$TaskDefinition = terraform output -raw bootstrap_task_definition
$Subnets = terraform output -raw bootstrap_subnets
$TaskSecurityGroup = terraform output -raw task_security_group
$Network = "awsvpcConfiguration={subnets=[$Subnets],securityGroups=[$TaskSecurityGroup],assignPublicIp=ENABLED}"
$Run = aws ecs run-task --cluster $Cluster --task-definition $TaskDefinition --launch-type FARGATE --network-configuration $Network --query "tasks[0].taskArn" --output text
if (-not $Run -or $Run -eq "None") { throw "Bootstrap task did not start. Check ECS stopped-task details and CloudWatch logs." }
aws ecs wait tasks-stopped --cluster $Cluster --tasks $Run
aws ecs describe-tasks --cluster $Cluster --tasks $Run --query "tasks[0].{lastStatus:lastStatus,exitCode:containers[0].exitCode,reason:stoppedReason}" --output table
```

The task is safe to rerun: it does not reset an existing Review II schema. Confirm `exitCode` is `0`. If it is nonzero, inspect `/ecs/dmers/course-bootstrap` in CloudWatch Logs before continuing.

### 5. Open and verify the app

```powershell
terraform output -raw app_url
terraform output -raw backend_health_url
```

Open the first URL in a browser. The second should return JSON with `status: "ok"`, PostgreSQL connected, and the Review II database connected. To retrieve the generated initial admin password without printing the other secret fields, run:

```powershell
$SecretName = terraform output -raw application_secret_name
$AppSecret = aws secretsmanager get-secret-value --secret-id $SecretName --query SecretString --output text | ConvertFrom-Json
Write-Output "Admin email: $($AppSecret.DMERS_BOOTSTRAP_ADMIN_EMAIL)"
Write-Output "Admin password: $($AppSecret.DMERS_BOOTSTRAP_ADMIN_PASSWORD)"
```

Change the initial admin password after signing in. The password is generated once and remains unchanged by ordinary Terraform applies.

## Updating the AWS deployment

Build and push a new `latest` image using the image commands above, then run `terraform apply -var="image_tag=latest"` to register the task definition and roll the ECS services. Force a new rollout when replacing an image without changing the tag:

```powershell
$Cluster = terraform output -raw ecs_cluster_name
aws ecs update-service --cluster $Cluster --service backend --force-new-deployment
aws ecs update-service --cluster $Cluster --service frontend --force-new-deployment
```

## Before using beyond a course demo

- Add a Route 53 domain and ACM certificate, configure an HTTPS (443) ALB listener and redirect HTTP to HTTPS. The current listener is HTTP-only and must not carry real credentials or incident data over the public Internet.
- Change the seeded demo passwords and the application's account bootstrap behavior for production.
- Use a least-privilege application database user instead of the RDS master user; run schema migrations through a controlled deployment step.
- Consider private ECS subnets with VPC endpoints or NAT, multi-AZ RDS, deletion protection, alarms, backups, and stricter inbound access.
- Set `desired_count` and database sizing for measured load; review AWS regional prices before scaling.

## Tear down

From `aws/`, run `terraform destroy` only when you intend to remove the demo. The RDS resource has deletion protection disabled and `skip_final_snapshot` enabled to keep course cleanup simple; export needed data first. The ECR repositories retain images unless deleted separately.
