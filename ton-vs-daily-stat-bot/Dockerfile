FROM ubuntu:20.04

RUN apt-get update
RUN DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC apt-get -y install tzdata
RUN apt-get install --yes curl wget
RUN apt-get install --yes python3 python3-pip git

ADD requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
COPY . /app

ENTRYPOINT [ "/app/entrypoint.py" ]
