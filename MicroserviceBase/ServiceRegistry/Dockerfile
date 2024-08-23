# Set arguments
ARG BASE_CONTAINER=python:3.9

# Set the base image. 
FROM --platform=linux/amd64 $BASE_CONTAINER

# Adds metadata to image.
LABEL maintainer="Thomas"

ARG USE_PROXY
ARG PROXY

# USER root
RUN apt-get update && apt-get install -y && apt-get clean

# Make a directory for our app
WORKDIR /MicroserviceBase

# Install dependencies
COPY requirements.txt .

RUN if [ "$USE_PROXY" = "true" ]; then \
        pip --proxy $PROXY install --upgrade pip && pip install --proxy $PROXY -r requirements.txt; \
    else \
        pip install --upgrade pip && pip install -r requirements.txt; \
    fi

# Copy source code
COPY . .

# Run the application
CMD ["python", "ServiceRegistry.py"]