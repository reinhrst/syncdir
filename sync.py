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

# list of globs of file and directory names to exclude
EXCLUDE = (".git", ".*.swp", ".virtualenv")


class SyncEventHandler(watchdog.events.FileSystemEventHandler):
    def __init__(self, src, dst):
        self.queue = Queue.Queue()
        self.src = os.path.abspath(src)
        self.targetisremote = (dst.count(":") > 0)
        if self.targetisremote:
            parts = dst.split(":", 1)
            self.dst = parts[0] + ":" + subprocess.check_output([
                "ssh", parts[0], "readlink", "-f", parts[1]]).strip()
            logging.info("Target is remote %s", self.dst)
        else:
            self.dst = os.path.abspath(dst)
        minlength = min(len(self.src), len(self.dst))
        if not os.path.isdir(self.src):
            raise Exception('"%s" is not a directory' % self.src)
        if self.targetisremote:
            usernamehost, remotedst = self.dst.split(":", 1)
            try:
                subprocess.check_call([
                    "ssh", usernamehost, "test", "-d", remotedst])
            except subprocess.CalledProcessError:
                raise Exception("Remote dir %s is not a directory" %
                                remotedst)
        else:
            if not os.path.isdir(self.dst):
                raise Exception('"%s" is not a directory' % self.dst)
            if self.src[0:minlength] == self.dst[0:minlength]:
                raise Exception("Source and destination cannot be "
                                "subdirectories of one another")

        self.queue.put(("initialSync",))

    def initialSync(self):
        self.emptyQueue()
        logging.info("Constructed, copying....")
        cmd = ["rsync", "-rpcv", "--del", self.src + "/", self.dst]
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
                self.queue.get(block=True, timeout=1)
                self.queue.task_done()
        except Queue.Empty:
            return

    def dequeue(self):
        try:
            cmd = self.queue.get(block=True, timeout=1)
        except Queue.Empty:
            return
        time.sleep(0.05)
        if self.queue.qsize() > 10:
            self.queue.task_done()
            self.initialSync()
            return
        logging.info("doing command %s" % repr(cmd))
        if len(cmd) == 1 and cmd[0] == "initialSync":
            self.initialSync()
            return
        if cmd[0] not in ("rsync", "scp") and self.targetisremote:
            usernamehost, target = cmd[-1].split(":", 1)
            cmd = ("ssh", usernamehost) + tuple(cmd[:-1]) + (target, )
        result = subprocess.call(cmd)
        self.queue.task_done()
        if result != 0:
            for i in range(5):
                subprocess.call(('tput', 'bel'))
                time.sleep(0.4)
            self.initialSync()

    def get_target(self, source):
        target = source.replace(self.src, self.dst)
        return target

    def on_created(self, event):
        if self.isExcluded(event.src_path):
            logging.info("created: excluded: %s" % event.src_path)
            return
        target = self.get_target(event.src_path)
        if event.is_directory:
            self.queue.put(("mkdir", "-v", target))
        else:
            self.queue.put(("scp", event.src_path, target))

    def on_deleted(self, event):
        if self.isExcluded(event.src_path):
            logging.info("deleted: excluded: %s" % event.src_path)
            return
        target = self.get_target(event.src_path)
        self.queue.put(("rm", "-rv", target))

    def on_modified(self, event):
        if self.isExcluded(event.src_path):
            logging.info("modified: excluded: %s" % event.src_path)
            return
        target = self.get_target(event.src_path)
        if event.is_directory:
            # directory modified on OSX may mean that a file got changed in the
            # dir :(
            cmd = ["rsync", "-rpcv", "--exclude",  "/*/*",
                   event.src_path + "/", target]
            for fn in EXCLUDE:
                cmd += ["--exclude", fn]
            self.queue.put(cmd)
        else:
            self.on_created(event)

    def on_moved(self, event):
        if self.isExcluded(event.src_path) and \
                self.isExcluded(event.dest_path):
            logging.info("move: excluded from all: %s" % event.src_path)
            return
        if self.isExluded(event.dest_path):
            logging.info("move: excluded from dest_path: %s, so remove event" %
                         event.src_path)
            self.on_deleted(event)
            return
        if self.isExcluded(event.src_path):
            logging.info("move: excluded from src_path, so create event: %s" %
                         event.dest_path)
            event.src_path = event.dest_path
            self.on_created(event)
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
            event_handler.dequeue()
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
