FROM python:3.7

WORKDIR /opt/
COPY dummy.py dummy.py
COPY requirements.txt requirements.txt

RUN pip install -r requirements.txt

CMD python -u dummy.py
