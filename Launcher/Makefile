PRODUCT    := NumBridgeLauncher
BUILD_DIR  := .build/release
DIST       := ../dist
APP        := $(DIST)/$(PRODUCT).app
CONTENTS   := $(APP)/Contents

.PHONY: all build bundle run install clean

all: bundle

build:
	swift build -c release

## Assemble the .app bundle from the SPM build output.
## Codesigns ad-hoc (sufficient for local use; replace `-` with Developer ID for distribution).
bundle: build
	@rm -rf $(APP)
	@mkdir -p $(CONTENTS)/MacOS $(CONTENTS)/Resources
	cp $(BUILD_DIR)/$(PRODUCT)                        $(CONTENTS)/MacOS/
	cp Info.plist                                      $(CONTENTS)/
	# Symlink the sibling server dir so ServerManager can find it without bundling Python
	ln -sfn $(abspath ../server)                      $(DIST)/server
	codesign --force --deep --sign - $(APP)
	@echo "Built: $(APP)"

## Build, then open the app directly from dist/ (handy during development)
run: bundle
	open $(APP)

## Install to /Applications and launch
install: bundle
	cp -R $(APP) /Applications/
	open /Applications/$(PRODUCT).app
	@echo "Installed: /Applications/$(PRODUCT).app"

clean:
	swift package clean
	rm -rf $(DIST)
