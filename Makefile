# Build the image that runs on the Raspberry Pi (see scripts/home-image.sh).
# Deploying it is done from the raspberry repository: ./pi release peugeot

.PHONY: test image image-name

test:
	@scripts/home-image.sh test

# The tests run first; SKIP_TESTS=1 builds without them.
image:
	@[ "$(SKIP_TESTS)" = "1" ] || scripts/home-image.sh test
	@scripts/home-image.sh image

image-name:
	@scripts/home-image.sh name
