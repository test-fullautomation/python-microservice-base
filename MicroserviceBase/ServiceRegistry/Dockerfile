# Set arguments
ARG BASE_CONTAINER=python:3.9
ARG HTTP_PROXY=http://rb-proxy-apac.bosch.com:8080
ARG HTTPS_PROXY=http://rb-proxy-apac.bosch.com:8080
ARG NO_PROXY=localhost, 127.0.0.*, 10.*, 192.168.*, *.bosch.com

# Set the base image. 
FROM --platform=linux/amd64 $BASE_CONTAINER

# Adds metadata to image.
LABEL maintainer="Thomas"

# USER root
RUN apt-get update && apt-get install -y && apt-get clean


# Make a directory for our app
WORKDIR /MicroserviceClewareSwitch

# Install dependencies
COPY requirements.txt .

RUN pip install --upgrade pip && pip install -r requirements.txt


# Copy source code
COPY . .

# Run the application
CMD ["python", "ServiceRegistry.py"]