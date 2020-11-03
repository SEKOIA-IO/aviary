FROM python:3.7

RUN apt update && \
      apt install -y curl netcat && \
      curl -LO https://storage.googleapis.com/kubernetes-release/release/`curl -s https://storage.googleapis.com/kubernetes-release/release/stable.txt`/bin/linux/amd64/kubectl && \
      chmod +x ./kubectl && \
      mv ./kubectl /usr/local/bin/kubectl

WORKDIR /app/
COPY requirements.txt /tmp/requirements.txt
RUN pip install --pre -Ur /tmp/requirements.txt

COPY python /app/

CMD ["python3", "-u", "aviary.py"]
