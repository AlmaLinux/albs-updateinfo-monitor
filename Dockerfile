FROM fedora:37

RUN mkdir -p /code && \
    dnf update -y && \
    dnf install python311 python3-pip libmodulemd python3-libmodulemd \
                python3-libmodulemd1 modulemd-tools python-gobject -y && \
    dnf clean all && \
    pip3 install poetry && \
    curl https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh -o wait_for_it.sh && \
    chmod +x wait_for_it.sh
COPY ./ /code
WORKDIR /code
RUN poetry config virtualenvs.options.system-site-packages true && \
    poetry install
CMD ["/bin/bash", "-c", "poetry run python ./updateinfo_monitor/cli.py"]

