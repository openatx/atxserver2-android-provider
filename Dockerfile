FROM python:3.9

RUN curl -sL https://deb.nodesource.com/setup_11.x | bash -
RUN apt-get install -y nodejs wget

ADD . /app
WORKDIR /app

RUN sh install-adb.sh

RUN npm install
RUN pip install uv && uv sync

ENTRYPOINT []
CMD ["uv", "run", "main.py", "--server", "http://localhost:4000"]
