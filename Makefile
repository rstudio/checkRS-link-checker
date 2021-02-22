DIRNAME=$(shell basename $(CURDIR))
PYTESTOPTS?=

PACKAGE_VERSION := $(shell pipenv run python setup.py --version)
RELEASE_ARTIFACT_WHL := dist/checkrs_linkto-$(PACKAGE_VERSION)-py3-none-any.whl
RELEASE_ARTIFACT_TGZ := dist/checkrs_linkto-$(PACKAGE_VERSION).tar.gz

# NOTE: This Makefile does not support running with concurrency (-j XX).
.NOTPARALLEL:

.PHONY: all
all:

.PHONY: pyenv
pyenv:
	pyenv install 3.9.0 --skip-existing; \
	pyenv virtualenv-delete ${DIRNAME} || true; \
	pyenv virtualenv 3.9.0 ${DIRNAME}; \
	pyenv local ${DIRNAME};

.PHONY: deps
deps:
	python3 -m pip install pipenv;
	pipenv install --dev;

.PHONY: test
test:
	pipenv run pytest --junitxml=result.txt test/ ${PYTESTOPTS}

.PHONY: sdist
sdist:
	pipenv run python3 setup.py sdist
	shasum ${RELEASE_ARTIFACT_TGZ} > ${RELEASE_ARTIFACT_TGZ}.sha

.PHONY: bdist
bdist:
	pipenv run python3 setup.py bdist_wheel
	shasum ${RELEASE_ARTIFACT_WHL} > ${RELEASE_ARTIFACT_WHL}.sha

.PHONY: release-artifact
release-artifact: bdist
	@echo "::set-output name=package_version::$(PACKAGE_VERSION)"
	@echo "::set-output name=tarball::$(FUZZBUCKET_RELEASE_ARTIFACT)"
	@echo "::set-output name=tarball_basename::$(notdir $(FUZZBUCKET_RELEASE_ARTIFACT))"


.PHONY: install
install:
	pipenv run pip install --upgrade .

.PHONY: clean
clean:
	rm -f *.log
	rm -rf build/ dist/ src/*.egg-info src/*.egg
	find . \( -name '*.pyc' -or -name '*.pyo' \) -print -delete
	find . -name '__pycache__' -print -delete
