# PyScopeGrab
Little Python script for talking to and retrieving data from Fluke ScopeMeter 105, mainly serial capture & PNG export. 

- CLI usage: `pyscopegrap [-h] [--withgui] ...`
- GUI: install the optional extra `pip install .[gui]` and run `pyscopegrap --withgui`

## Install (editable / dev)
```bash
pip install -e .
```

## Requirements
- Python 3.9+
- `pyserial`, `Pillow`
- Optional GUI: `PyQt6`

## Run
```bash
# CLI grab (defaults pulled from user settings)
pyscopegrab -g --out screenshot.png

# Launch GUI
pyscopegrab --withgui
```

## Some intressting links
https://www.stevenmerrifield.com/scopegrab.html

https://github.com/sjm126

https://www.fluke.com/en-us/product/accessories/adapters/fluke-pm8907

https://sourceforge.net/projects/scopegrab32/

https://www.mikrocontroller.net/attachment/249364/pm97qp.py

https://www.fluke.com/en-us/product/accessories/adapters/fluke-pm8907

https://sourceforge.net/p/scopegrab32/discussion/421406/thread/7abc7b05/

https://www.itsonlyaudio.com/measurement/fluke-123-opto-isolated-cable/

## debugging tipps
python3 -m pyscopegrap -w -o test.png --tap raw.bin -v
python3 -m pyscopegrap --sniff 8 --tap raw.bin -v  

python3 -m pyscopegrap --help            
python3 -m pyscopegrap -o test.png  
python3 -m pyscopegrap --withgu
python3 -m pyscopegrap --withgui

### Minimal console output only:
python3 -m pyscopegrap
(Console shows INFO+ messages.)

### Console + file logging (file gets DEBUG details, console gets INFO):
python3 -m pyscopegrap -l --log-file /tmp/psg.log

### Make console verbose too:
python3 -m pyscopegrap -l -v


### File-only logging (no console output):
python3 -m pyscopegrap -l --quiet


