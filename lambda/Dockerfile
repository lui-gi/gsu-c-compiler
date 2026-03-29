FROM public.ecr.aws/lambda/python:3.12

# Install GCC toolchain. The Lambda base image uses Amazon Linux 2023 (dnf).
# glibc-static allows student programs to link statically if needed.
RUN dnf install -y gcc glibc-static && \
    dnf clean all

COPY handler.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.handler"]
