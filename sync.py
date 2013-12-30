#!/usr/bin/python

import sys
import os
import time
import logging
from watchdog.observers import Observer
import watchdog.events
import subprocess
import Queue
import os.path
import fnmatch

EXCLUDE=(".git", ".*.swp") #list of file and directory names to exclude

class SyncEventHandler(watchdog.events.FileSystemEventHandler):
    def __init__(self, src, dst):
        self.queue = Queue.Queue()
        self.src = os.path.abspath(src)
        self.dst = os.path.abspath(dst)
        minlength = min(len(self.src), len(self.dst))
        if not os.path.isdir(self.src):
            raise Exception('"%s" is not a directory' % self.src)
        if not os.path.isdir(self.dst):
            raise Exception('"%s" is not a directory' % self.dst)

        if self.src[0:minlength] == self.dst[0:minlength]:
            raise Exception("Source and destination cannot be subdirectories of each other")

        self.queue.put(("initialSync",))

    def initialSync(self):
        self.emptyQueue()
        logging.info("Constructed, copying....");
        cmd = ["rsync", "-rpcv", "--del", "--delete-excluded", self.src + "/", self.dst]
        for fn in EXCLUDE:
            cmd += ["--exclude", fn]
        result = subprocess.call(cmd)
        if result != 0:
            for i in range(5):
                subprocess.call(('tput', 'bel'))
                time.sleep(0.4)
            raise Exception("Crash, should always return 0!")
        logging.info("done!")

    def isExcluded(self, source):
        pathpart = source.replace(self.src, "").split(os.sep)
        for fn in EXCLUDE:
            for pp in pathpart:
                if fnmatch.fnmatch(pp, fn):
                    return True
        return False

        

    def emptyQueue(self):
        try:
            while True:
                self.queue.get(block=True, timeout=1);
                self.queue.task_done()
        except Queue.Empty:
            return
 
    def dequeue(self):
        try:
            cmd = self.queue.get(block=True, timeout=1);
        except Queue.Empty:
            return
        time.sleep(0.05)
        if self.queue.qsize() > 10:
            self.queue.task_done()
            self.initialSync()
            return
        logging.info("doing command %s" %repr(cmd))
        if len(cmd) == 1 and cmd[0] == "initialSync":
            self.initialSync();
            return

        result = subprocess.call(cmd)
        self.queue.task_done()
        if result != 0:
            for i in range(5):
                subprocess.call(('tput', 'bel'))
                time.sleep(0.4)
            self.initialSync();

    def get_target(self, source):
        target = source.replace(self.src, self.dst);
        return target


    def on_created(self, event):
        if self.isExcluded(event.src_path):
            return
        target = self.get_target(event.src_path)
        if event.is_directory:
            self.queue.put(("mkdir", "-v", target))
        else:
            self.queue.put(("cp", "-av", event.src_path, target))

    def on_deleted(self, event):
        if self.isExcluded(event.src_path):
            return
        target = self.get_target(event.src_path)
        self.queue.put(("rm", "-rv", target))

    def on_modified(self, event):
        if self.isExcluded(event.src_path):
            return
        target = self.get_target(event.src_path)
        if event.is_directory:
            self.queue.put(("touch", target))
        else:
            self.on_created(event)

    def on_moved(self, event):
        if self.isExcluded(event.src_path):
            return
        target_src = self.get_target(event.src_path)
        target_dst = self.get_target(event.dest_path)
        self.queue.put(("mv", target_src, target_dst))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')
    if len(sys.argv) != 3:
        print "Call %s srcdir dstdir" % sys.argv[0]
        sys.exit(1)
    event_handler = SyncEventHandler(sys.argv[1], sys.argv[2])
    observer = Observer()
    observer.schedule(event_handler, sys.argv[1], recursive=True)
    observer.start()
    try:
        while True:
            event_handler.dequeue();
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
