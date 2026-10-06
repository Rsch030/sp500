"""Headless Wine supervisor. No public desktop or RPC port. Demo/read-only default."""
import os, sys, time, json, signal, subprocess, zipfile, shutil, socket
from pathlib import Path

ROOT=Path('/data'); STATE=ROOT/'runtime-state.json'
def stage(name):
    print("[MT5 runtime]",name,flush=True)
    tmp=STATE.with_suffix('.tmp');tmp.write_text(json.dumps({'stage':name,'updated_at':time.time(),'mode':os.getenv('BRIDGE_MODE','DRY_RUN')}));tmp.replace(STATE)

def run(args,timeout=240):
    subprocess.run(args,check=True,timeout=timeout)

def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    processes=[]
    def stop(*args):
        for p in processes:
            if p.poll() is None: p.terminate()
        subprocess.run(['wineserver','-k'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    stage('STARTING')
    processes.append(subprocess.Popen([sys.executable,'-m','mt5_bridge.server']))
    processes.append(subprocess.Popen(['Xvfb',':99','-screen','0','1280x720x24','-nolisten','tcp']))
    # Wait for the virtual display socket, without opening a remote desktop port.
    deadline=time.monotonic()+15
    while not Path('/tmp/.X11-unix/X99').exists():
        if time.monotonic()>deadline: raise RuntimeError('Virtual display startup failed')
        time.sleep(.2)
    try:
        prefix=Path(os.environ['WINEPREFIX'])
        seed=Path('/opt/wine-seed')
        if not (prefix/'system.reg').exists() and seed.exists() and prefix!=seed:
            stage('PREPARING_TERMINAL');shutil.copytree(seed,prefix,dirs_exist_ok=True,symlinks=True)
        if not (prefix/'system.reg').exists():
            stage('INITIALIZING_WINE'); run(['/usr/lib/wine/wine64','wineboot.exe','-u'],120)
        py=prefix/'drive_c/Python312'; exe=py/'python.exe'
        if not exe.exists():
            py.mkdir(parents=True,exist_ok=True)
            with zipfile.ZipFile('/opt/installers/python.zip') as z:z.extractall(py)
            pth=py/'python312._pth';pth.write_text(pth.read_text().replace('#import site','import site')+'\nZ:\\app\n')
        marker=py/'bridge-ready'
        if not marker.exists():
            stage('INSTALLING_WINDOWS_PYTHON_PACKAGES')
            run(['/usr/lib/wine/wine64',str(exe),'Z:\\opt\\installers\\get-pip.py'],240)
            run(['/usr/lib/wine/wine64',str(exe),'-m','pip','install','-r','Z:\\app\\mt5_bridge\\requirements-windows.txt'],360)
            marker.touch()
        terminals=list((prefix/'drive_c/Program Files').glob('*/terminal64.exe'))
        if len(terminals)!=1:
            stage('INSTALLING_FTMO_MT5')
            proc=subprocess.Popen(['/usr/lib/wine/wine64','/opt/installers/ftmo5setup.exe','/auto'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            deadline=time.monotonic()+300
            while time.monotonic()<deadline:
                terminals=list((prefix/'drive_c/Program Files').glob('*/terminal64.exe'))
                if len(terminals)==1 and terminals[0].stat().st_size>1_000_000: break
                time.sleep(2)
            if len(terminals)!=1: raise RuntimeError('MT5 unattended installer did not complete')
            run(['wineserver','-k'],30)
        terminal=terminals[0]
        stage('CHECKING_WINDOWS_IMPORTS')
        run(['/usr/lib/wine/wine64',str(exe),'-c','import numpy, MetaTrader5, requests; print("Windows imports OK", numpy.__version__, MetaTrader5.__version__, flush=True)'],60)
        if os.getenv('BOOTSTRAP_ONLY')=='1':
            stage('IMAGE_READY');stop()
        os.environ['MT5_PATH']='C:\\'+str(terminal.relative_to(prefix/'drive_c')).replace('/','\\')
        os.environ['MT5_PORTABLE']='1'
        os.environ['MT5_STATE_DIR']='Z:\\data\\worker-state'
        os.environ.setdefault('BRIDGE_MODE','DRY_RUN')
        os.environ.setdefault('BRIDGE_URL','https://'+os.environ.get('RAILWAY_PUBLIC_DOMAIN','mt5-bridge-production-2160.up.railway.app'))
        while not all(os.environ.get(k) for k in ('MT5_LOGIN','MT5_SERVER','MT5_PASSWORD')):
            stage('NEED_MT5_CREDENTIALS');time.sleep(30)
        stage('CONNECTING_MT5')
        # Windows Python needs Windows paths even when launched from Linux.
        worker=subprocess.Popen(['/usr/lib/wine/wine64',str(exe),'Z:\\app\\mt5_bridge\\worker.py'])
        processes.append(worker)
        while True:
            if worker.poll() is not None: raise RuntimeError('Windows worker exited')
            if processes[0].poll() is not None: raise RuntimeError('Signal server exited')
            time.sleep(5)
    except Exception as exc:
        stage('BOOTSTRAP_FAILED_'+type(exc).__name__)
        print('Wine bootstrap failed:',type(exc).__name__,flush=True)
        for p in processes:
            if p.poll() is None:p.terminate()
        subprocess.run(['wineserver','-k'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        raise SystemExit(1)

if __name__=='__main__':main()
