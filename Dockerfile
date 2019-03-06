FROM python:3

RUN curl -sL https://deb.nodesource.com/setup_11.x | bash -
RUN apt-get install -y nodejs adb

ADD . /app
WORKDIR /app
RUN npm install
RUN pip install -r requirements.txt

ENTRYPOINT []
CMD ["python", "main.py", "--server", "http://localhost:4000"]
