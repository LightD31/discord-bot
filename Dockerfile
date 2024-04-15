FROM python:3.11.3

# we want stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# add the path to pythonpath
ENV PYTHONPATH "${PYTHONPATH}:/app"

# install uvloop for faster asyncio
RUN pip3.11 install uvloop

# install the requirements
COPY ./requirements.txt /app/requirements.txt
RUN pip3.11 install --upgrade pip
RUN pip3.11 install --upgrade -r /app/requirements.txt

# copy over the source files
COPY ./ /app/

# start the bot
WORKDIR /app
CMD ["python3.11", "main.py"]
