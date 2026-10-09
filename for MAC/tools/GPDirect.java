import java.io.InputStream;
import java.io.OutputStream;
import java.net.Socket;
import apdu4j.core.BIBO;
import apdu4j.core.BIBOException;
import pro.javacard.gptool.GPTool;

public class GPDirect {
    public static void main(String[] args) {
        String host = "127.0.0.1";
        int port = 35963;

        try (Socket sock = new Socket(host, port)) {
            sock.setTcpNoDelay(true);
            InputStream in = sock.getInputStream();
            OutputStream out = sock.getOutputStream();

            BIBO bibo = new BIBO() {
                @Override
                public byte[] transceive(byte[] apdu) throws BIBOException {
                    try {
                        byte[] hdr = new byte[] { (byte) (apdu.length >> 8), (byte) (apdu.length & 0xFF) };
                        out.write(hdr);
                        out.write(apdu);
                        out.flush();

                        byte[] rxHdr = in.readNBytes(2);
                        if (rxHdr.length < 2) {
                            throw new BIBOException("Socket closed by card bridge");
                        }
                        int len = ((rxHdr[0] & 0xFF) << 8) | (rxHdr[1] & 0xFF);
                        byte[] resp = in.readNBytes(len);
                        return resp;
                    } catch (Exception e) {
                        throw new BIBOException(e.getMessage(), e);
                    }
                }

                @Override
                public void close() {
                    try {
                        sock.close();
                    } catch (Exception ignored) {}
                }
            };

            GPTool tool = new GPTool();
            int exitCode = tool.run(bibo, args);
            System.exit(exitCode);
        } catch (Exception e) {
            System.err.println("[GPDirect Error] Could not connect to bridge at " + host + ":" + port);
            System.err.println("Make sure start_decard_mac.sh is running in another terminal!");
            System.exit(1);
        }
    }
}
