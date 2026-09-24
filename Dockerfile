FROM apache/airflow:3.3.0

USER root

ARG TARGETARCH
ARG TERRAFORM_VERSION=1.9.8

RUN apt-get update && apt-get install -y curl unzip \
    && curl -fsSL -o terraform.zip https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip \
    && unzip terraform.zip -d /usr/local/bin \
    && rm terraform.zip \
    && curl -sSLO https://github.com/terraform-linters/tflint/releases/latest/download/tflint_linux_${TARGETARCH}.zip \
    && unzip tflint_linux_${TARGETARCH}.zip -d /usr/local/bin \
    && rm tflint_linux_${TARGETARCH}.zip \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

USER airflow

COPY --chown=airflow:root .tflint.hcl /opt/airflow/.tflint.hcl
RUN cd /opt/airflow && tflint --init

COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt