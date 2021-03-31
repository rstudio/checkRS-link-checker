FROM python:3.9.2-slim-buster
MAINTAINER RStudio Quality <qa+checkrs-linkto@rstudio.com>

ARG VERSION=0.0.0

RUN python3 -m pip install pipenv;

# Copy source files to image temp dir.
ENV TEMP_DIR /tmp/install/
COPY Pipfile Pipfile.lock dist $TEMP_DIR

RUN set -ex; \
    cd $TEMP_DIR; \
    pipenv install --system; \
    python3 -m pip install checkrs_linkto-${VERSION}-py3-none-any.whl;

# remove installation files
RUN rm -rf $TEMP_DIR
