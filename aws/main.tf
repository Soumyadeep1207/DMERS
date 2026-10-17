terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project   = "DMERS"
      ManagedBy = "Terraform"
    }
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_rds_engine_version" "postgres16" {
  engine         = "postgres"
  version_prefix = "16."
  default_only   = true
}

locals {
  name = var.project_name
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)
  public_cidrs  = ["10.40.0.0/24", "10.40.1.0/24"]
  private_cidrs = ["10.40.10.0/24", "10.40.11.0/24"]
  container_env_secret = jsonencode({
    DATABASE_URL                    = "postgresql://dmers_app:${random_password.app_db.result}@${aws_db_instance.dmers.address}:5432/dmers?sslmode=require"
    COURSE_DATABASE_URL             = "postgresql://dmers_app:${random_password.app_db.result}@${aws_db_instance.dmers.address}:5432/dmers_course?sslmode=require"
    SECRET_KEY                      = random_password.flask_secret.result
    DMERS_BOOTSTRAP_ADMIN_EMAIL     = "admin@rescue.ai"
    DMERS_BOOTSTRAP_ADMIN_PASSWORD  = random_password.admin.result
    DMERS_SEED_DEMO_DATA            = "false"
    APP_DB_USER                     = "dmers_app"
    APP_DB_PASSWORD                 = random_password.app_db.result
  })
}

variable "aws_region" {
  description = "AWS region for the DMERS deployment."
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Short prefix used for AWS resource names."
  type        = string
  default     = "dmers"
}

variable "db_username" {
  description = "RDS master username used by the demo deployment."
  type        = string
  default     = "dmers_admin"
}

variable "db_instance_class" {
  description = "RDS PostgreSQL instance class; check current regional availability and pricing."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "Initial encrypted RDS storage in GiB."
  type        = number
  default     = 20
}

variable "desired_count" {
  description = "Number of Fargate tasks per web service. Set to 1 for a low-cost demo."
  type        = number
  default     = 1
}

variable "image_tag" {
  description = "Container image tag already pushed to the three ECR repositories."
  type        = string
  default     = "latest"
}

resource "aws_vpc" "dmers" {
  cidr_block           = "10.40.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = { Name = "${local.name}-vpc" }
}

resource "aws_internet_gateway" "dmers" {
  vpc_id = aws_vpc.dmers.id
  tags   = { Name = "${local.name}-igw" }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.dmers.id
  availability_zone       = local.azs[count.index]
  cidr_block              = local.public_cidrs[count.index]
  map_public_ip_on_launch = true
  tags                    = { Name = "${local.name}-public-${count.index + 1}" }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.dmers.id
  availability_zone = local.azs[count.index]
  cidr_block        = local.private_cidrs[count.index]
  tags              = { Name = "${local.name}-private-${count.index + 1}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.dmers.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.dmers.id
  }
  tags = { Name = "${local.name}-public" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_db_subnet_group" "dmers" {
  name       = "${local.name}-db-subnets"
  subnet_ids = aws_subnet.private[*].id
  tags       = { Name = "${local.name}-db-subnets" }
}

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Public web access through the DMERS load balancer"
  vpc_id      = aws_vpc.dmers.id
  ingress {
    description = "HTTP web access"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "tasks" {
  name        = "${local.name}-tasks"
  description = "Only the ALB can access DMERS service containers"
  vpc_id      = aws_vpc.dmers.id
  ingress {
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  ingress {
    from_port       = 5000
    to_port         = 5000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "database" {
  name        = "${local.name}-database"
  description = "PostgreSQL access only from DMERS tasks"
  vpc_id      = aws_vpc.dmers.id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.tasks.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "random_password" "flask_secret" {
  length  = 48
  special = false
}

resource "random_password" "app_db" {
  length  = 32
  special = false
}

resource "random_password" "admin" {
  length  = 24
  special = false
}

resource "aws_secretsmanager_secret" "db_password" {
  name                    = "${local.name}/database-password"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = random_password.db.result
}

resource "aws_secretsmanager_secret" "application" {
  name                    = "${local.name}/application-environment"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "application" {
  secret_id     = aws_secretsmanager_secret.application.id
  secret_string = local.container_env_secret
}

resource "aws_db_instance" "dmers" {
  identifier                  = "${local.name}-postgres"
  engine                      = "postgres"
  engine_version              = data.aws_rds_engine_version.postgres16.version
  instance_class              = var.db_instance_class
  allocated_storage           = var.db_allocated_storage
  max_allocated_storage       = max(100, var.db_allocated_storage)
  storage_encrypted           = true
  db_name                     = "dmers"
  username                    = var.db_username
  password                    = random_password.db.result
  port                        = 5432
  db_subnet_group_name        = aws_db_subnet_group.dmers.name
  vpc_security_group_ids      = [aws_security_group.database.id]
  publicly_accessible         = false
  multi_az                    = false
  backup_retention_period     = 7
  auto_minor_version_upgrade  = true
  deletion_protection         = false
  skip_final_snapshot         = true
  apply_immediately           = false
  tags                        = { Name = "${local.name}-postgres" }
}

resource "aws_ecr_repository" "backend" {
  name                 = "${local.name}-backend"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_repository" "frontend" {
  name                 = "${local.name}-frontend"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_repository" "bootstrap" {
  name                 = "${local.name}-course-bootstrap"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${local.name}/backend"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/ecs/${local.name}/frontend"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "bootstrap" {
  name              = "/ecs/${local.name}/course-bootstrap"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "dmers" {
  name = "${local.name}-cluster"
}

data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

resource "aws_iam_role_policy_attachment" "execution_base" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "read_secrets" {
  name = "${local.name}-read-task-secrets"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [aws_secretsmanager_secret.application.arn, aws_secretsmanager_secret.db_password.arn]
    }]
  })
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "${local.name}-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  container_definitions = jsonencode([{
    name      = "backend"
    image     = "${aws_ecr_repository.backend.repository_url}:${var.image_tag}"
    essential = true
    portMappings = [{ containerPort = 5000, hostPort = 5000, protocol = "tcp" }]
    secrets = [
      { name = "DATABASE_URL", valueFrom = "${aws_secretsmanager_secret.application.arn}:DATABASE_URL::" },
      { name = "COURSE_DATABASE_URL", valueFrom = "${aws_secretsmanager_secret.application.arn}:COURSE_DATABASE_URL::" },
      { name = "SECRET_KEY", valueFrom = "${aws_secretsmanager_secret.application.arn}:SECRET_KEY::" },
      { name = "DMERS_BOOTSTRAP_ADMIN_EMAIL", valueFrom = "${aws_secretsmanager_secret.application.arn}:DMERS_BOOTSTRAP_ADMIN_EMAIL::" },
      { name = "DMERS_BOOTSTRAP_ADMIN_PASSWORD", valueFrom = "${aws_secretsmanager_secret.application.arn}:DMERS_BOOTSTRAP_ADMIN_PASSWORD::" },
      { name = "DMERS_SEED_DEMO_DATA", valueFrom = "${aws_secretsmanager_secret.application.arn}:DMERS_SEED_DEMO_DATA::" }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.backend.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "backend"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "frontend" {
  family                   = "${local.name}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn
  container_definitions = jsonencode([{
    name      = "frontend"
    image     = "${aws_ecr_repository.frontend.repository_url}:${var.image_tag}"
    essential = true
    portMappings = [{ containerPort = 8080, hostPort = 8080, protocol = "tcp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.frontend.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "frontend"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "bootstrap" {
  family                   = "${local.name}-course-bootstrap"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn
  container_definitions = jsonencode([{
    name      = "course-bootstrap"
    image     = "${aws_ecr_repository.bootstrap.repository_url}:${var.image_tag}"
    essential = true
    environment = [
      { name = "PGHOST", value = aws_db_instance.dmers.address },
      { name = "PGUSER", value = var.db_username },
      { name = "PGPORT", value = "5432" },
      { name = "PGSSLMODE", value = "require" }
    ]
    secrets = [
      { name = "PGPASSWORD", valueFrom = aws_secretsmanager_secret.db_password.arn },
      { name = "APP_DB_PASSWORD", valueFrom = "${aws_secretsmanager_secret.application.arn}:APP_DB_PASSWORD::" }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.bootstrap.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "bootstrap"
      }
    }
  }])
}

resource "aws_lb" "dmers" {
  name               = "${local.name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
}

resource "aws_lb_target_group" "frontend" {
  name        = "${local.name}-frontend"
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.dmers.id
  health_check {
    enabled             = true
    path                = "/health"
    matcher             = "200"
    healthy_threshold   = 2
    unhealthy_threshold = 4
    interval            = 30
  }
}

resource "aws_lb_target_group" "backend" {
  name        = "${local.name}-backend"
  port        = 5000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.dmers.id
  health_check {
    enabled             = true
    path                = "/health"
    matcher             = "200"
    healthy_threshold   = 2
    unhealthy_threshold = 4
    interval            = 30
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.dmers.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

resource "aws_lb_listener_rule" "backend_api" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }
  condition {
    path_pattern { values = ["/api", "/api/*"] }
  }
}

resource "aws_ecs_service" "backend" {
  name            = "backend"
  cluster         = aws_ecs_cluster.dmers.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 5000
  }
  depends_on = [aws_lb_listener.http, aws_lb_listener_rule.backend_api]
}

resource "aws_ecs_service" "frontend" {
  name            = "frontend"
  cluster         = aws_ecs_cluster.dmers.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 8080
  }
  depends_on = [aws_lb_listener.http]
}

output "app_url" {
  description = "HTTP URL for the DMERS application. Add ACM/TLS before using sensitive data publicly."
  value       = "http://${aws_lb.dmers.dns_name}"
}

output "backend_health_url" {
  description = "Backend health endpoint routed through the public load balancer."
  value       = "http://${aws_lb.dmers.dns_name}/api/health"
}

output "ecr_backend_url" { value = aws_ecr_repository.backend.repository_url }
output "ecr_frontend_url" { value = aws_ecr_repository.frontend.repository_url }
output "ecr_bootstrap_url" { value = aws_ecr_repository.bootstrap.repository_url }
output "ecs_cluster_name" { value = aws_ecs_cluster.dmers.name }
output "bootstrap_task_definition" { value = aws_ecs_task_definition.bootstrap.arn }
output "bootstrap_subnets" { value = join(",", aws_subnet.public[*].id) }
output "task_security_group" { value = aws_security_group.tasks.id }
output "application_secret_name" { value = aws_secretsmanager_secret.application.name }
