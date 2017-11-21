
# Instructions for installing dependencies

## Mac

First `cd` into `gt-text-common/pretex`.

```
brew update
brew install python2 python3 cairo py2cairo poppler
brew tap caskroom/cask
brew install caskroom/cask/fontforge
brew install ./inkscape.rb
pip2 install pdfrw
pip2 install ./pypoppler-0.12.2-jdr.tar.gz
pip3 install cssutils lxml bs4
```

## Debian-based linux

First `cd` into `gt-text-common/pretex`.

```
sudo apt-get install python-minimal python3-minimal python-pip python3-pip python-poppler fontforge libcairo2-dev
pip2 install ./pycairo-1.15.3.tar.gz`
pip2 install pdfrw`
pip3 install cssutils lxml bs4`
sudo apt-get build-dep inkscape`
sudo apt-get source inkscape`
cd inkscape-[version] && patch -p1 < ../inkscape.patch && dpkg-buildpkg -b
```

Then install the generated inkscape package.

