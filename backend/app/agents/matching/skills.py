"""Skill vocabulary + extraction. Canonical name -> (category, alias regexes)."""
import re

SKILLS: dict[str, tuple[str, list[str]]] = {
    "Python": ("language", [r"python"]),
    "Java": ("language", [r"java(?!script)"]),
    "Go": ("language", [r"golang", r"go(?= developer| engineer)"]),
    "Bash": ("language", [r"bash", r"shell scripting", r"shell script"]),
    "JavaScript": ("language", [r"javascript", r"node\.?js"]),
    "TypeScript": ("language", [r"typescript"]),
    "Django": ("framework", [r"django"]),
    "Django REST Framework": ("framework", [r"django rest framework", r"\bdrf\b"]),
    "FastAPI": ("framework", [r"fast ?api"]),
    "Flask": ("framework", [r"flask"]),
    "Spring Boot": ("framework", [r"spring ?boot"]),
    "React": ("framework", [r"react(?:\.js|js)?"]),
    "REST APIs": ("backend", [r"rest(?:ful)? ?apis?", r"\brest\b"]),
    "GraphQL": ("backend", [r"graphql"]),
    "Microservices": ("backend", [r"micro-?services?"]),
    "PostgreSQL": ("database", [r"postgres(?:ql)?"]),
    "MySQL": ("database", [r"mysql"]),
    "MongoDB": ("database", [r"mongo ?db"]),
    "Redis": ("database", [r"redis"]),
    "Kafka": ("messaging", [r"kafka"]),
    "RabbitMQ": ("messaging", [r"rabbit ?mq"]),
    "Celery": ("messaging", [r"celery"]),
    "Docker": ("containers", [r"docker"]),
    "Kubernetes": ("containers", [r"kubernetes", r"\bk8s\b"]),
    "Helm": ("containers", [r"\bhelm\b"]),
    "AWS": ("cloud", [r"\baws\b", r"amazon web services"]),
    "EKS": ("cloud", [r"\beks\b"]),
    "EC2": ("cloud", [r"\bec2\b"]),
    "S3": ("cloud", [r"\bs3\b"]),
    "IAM": ("cloud", [r"\biam\b"]),
    "VPC": ("cloud", [r"\bvpc\b"]),
    "Lambda": ("cloud", [r"aws lambda", r"\blambda functions?\b"]),
    "Azure": ("cloud", [r"\bazure\b"]),
    "GCP": ("cloud", [r"\bgcp\b", r"google cloud"]),
    "Terraform": ("iac", [r"terraform"]),
    "Ansible": ("iac", [r"ansible"]),
    "CloudFormation": ("iac", [r"cloud ?formation"]),
    "Pulumi": ("iac", [r"pulumi"]),
    "GitHub Actions": ("cicd", [r"github actions"]),
    "Jenkins": ("cicd", [r"jenkins"]),
    "GitLab CI": ("cicd", [r"gitlab ?ci"]),
    "ArgoCD": ("cicd", [r"argo ?cd", r"\bargo\b"]),
    "CI/CD": ("cicd", [r"ci ?/ ?cd", r"continuous integration", r"continuous delivery", r"continuous deployment"]),
    "Git": ("cicd", [r"\bgit\b"]),
    "DevSecOps": ("security", [r"devsecops"]),
    "SonarQube": ("security", [r"sonar ?qube", r"sonarcloud"]),
    "Trivy": ("security", [r"trivy"]),
    "Snyk": ("security", [r"snyk"]),
    "OWASP Dependency-Check": ("security", [r"owasp dependency.?check", r"dependency.?check"]),
    "OWASP": ("security", [r"owasp"]),
    "Vault": ("security", [r"hashicorp vault", r"\bvault\b"]),
    "Prometheus": ("observability", [r"prometheus"]),
    "Grafana": ("observability", [r"grafana"]),
    "SigNoz": ("observability", [r"signoz"]),
    "ELK": ("observability", [r"\belk\b", r"elasticsearch", r"kibana", r"logstash"]),
    "Datadog": ("observability", [r"datadog"]),
    "OpenTelemetry": ("observability", [r"open ?telemetry", r"\botel\b"]),
    "Linux": ("os", [r"linux", r"ubuntu", r"rhel", r"centos"]),
    "Nginx": ("infra", [r"nginx"]),
    "Networking": ("infra", [r"tcp/ip", r"\bdns\b", r"load balanc\w+", r"networking"]),
    "Istio": ("infra", [r"istio", r"service mesh"]),
}

_COMPILED = {name: re.compile("|".join(f"(?:{a})" for a in aliases), re.I)
             for name, (_, aliases) in SKILLS.items()}

# Skills implied by a broader one the candidate has (avoid flagging as "missing").
IMPLIED: dict[str, set[str]] = {
    "AWS": {"EC2", "S3", "IAM", "VPC"},
    "Kubernetes": {"Helm"},
    "GitHub Actions": {"CI/CD", "Git"},
    "Jenkins": {"CI/CD"},
    "DevSecOps": {"OWASP"},
    "Django REST Framework": {"REST APIs"},
    "OWASP Dependency-Check": {"OWASP"},
}


def extract_skills(text: str) -> list[str]:
    if not text:
        return []
    return [name for name, rx in _COMPILED.items() if rx.search(text)]


def canonicalize(skills: list[str]) -> set[str]:
    """Map free-form profile skills to canonical names and add implied skills."""
    out: set[str] = set()
    for s in skills:
        found = extract_skills(s)
        out.update(found or [s])
    for s in list(out):
        out |= IMPLIED.get(s, set())
    return out
