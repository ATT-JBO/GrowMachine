import socket
import fcntl
import struct

def isConnected():
    'returns true if we are connected, otherwise false'
    ifaces = ['eth0','wlan0']
    connected = []
    i = 0
    for ifname in ifaces:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            socket.inet_ntoa(fcntl.ioctl(s.fileno(),
                    0x8915,  # SIOCGIFADDR
                    struct.pack('256s', ifname[:15])
            )[20:24])
            connected.append(ifname)
            print "%s is connected" % ifname
        except:
            print "%s is not connected" % ifname

        i += 1

    return len(connected) > 0 #if we found an interface, then we are conneted