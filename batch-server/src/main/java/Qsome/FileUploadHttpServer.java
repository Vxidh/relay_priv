// File: Qsome/FileUploadHttpServer.java
package Qsome;

import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import org.json.JSONObject;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.concurrent.Executors;

public class FileUploadHttpServer {
    private HttpServer server;
    private String uploadDirectory;

    public FileUploadHttpServer(String host, int port, String uploadDir) throws IOException {
        this.uploadDirectory = uploadDir;
        Files.createDirectories(Paths.get(uploadDirectory));

        server = HttpServer.create(new InetSocketAddress(host, port), 0);
        server.createContext("/file_upload_callback", new FileUploadHandler());
        server.setExecutor(Executors.newFixedThreadPool(5));
    }

    public void start() {
        new Thread(() -> {
            System.out.println("FileUploadHttpServer: Starting server on " + server.getAddress());
            server.start();
        }).start();
    }

    public void stop() {
        if (server != null) {
            System.out.println("FileUploadHttpServer: Stopping server...");
            server.stop(0);
        }
    }

    class FileUploadHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            if ("POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                InputStream is = exchange.getRequestBody();
                String requestBody = new String(is.readAllBytes(), StandardCharsets.UTF_8);
                is.close();

                try {
                    JSONObject payload = new JSONObject(requestBody);
                    System.out.println("DEBUG: Incoming JSON payload: " + payload.toString(2));

                    JSONObject fileObj;
                    if (payload.has("file")) {
                        fileObj = payload.getJSONObject("file");
                    } else {
                        fileObj = new JSONObject();
                        fileObj.put("file_content", payload.optString("fileContentBase64"));
                        fileObj.put("filename", "unnamed_file_" + System.currentTimeMillis() + ".bin");
                        fileObj.put("request_id", payload.optString("requestId", "unknown"));
                    }

                    String fileName = fileObj.optString("filename");
                    String fileContentBase64 = fileObj.optString("file_content");
                    String requestId = fileObj.optString("request_id");

                    JSONObject fileDataForSave = new JSONObject();
                    fileDataForSave.put("fileName", fileName);
                    fileDataForSave.put("fileContentBase64", fileContentBase64);
                    fileDataForSave.put("requestId", requestId);

                    Path savedFilePath = Node.receiveFileAndSave(fileDataForSave, uploadDirectory);

                    String response = "{\"status\": \"success\", \"message\": \"File received and saved at " + savedFilePath.toAbsolutePath() + "\", \"requestId\": \"" + requestId + "\"}";
                    exchange.sendResponseHeaders(200, response.length());
                    OutputStream os = exchange.getResponseBody();
                    os.write(response.getBytes(StandardCharsets.UTF_8));
                    os.close();
                    System.out.println("FileUploadHttpServer: Successfully handled file upload for requestId: " + requestId);

                } catch (Exception e) {
                    System.err.println("FileUploadHttpServer: Error processing file upload: " + e.getMessage());
                    e.printStackTrace();
                    String response = "{\"status\": \"error\", \"message\": \"Error processing file upload: " + e.getMessage() + "\"}";
                    exchange.sendResponseHeaders(500, response.length());
                    OutputStream os = exchange.getResponseBody();
                    os.write(response.getBytes(StandardCharsets.UTF_8));
                    os.close();
                }
            } else {
                String response = "{\"status\": \"error\", \"message\": \"Only POST method supported.\"}";
                exchange.sendResponseHeaders(405, response.length());
                OutputStream os = exchange.getResponseBody();
                os.write(response.getBytes(StandardCharsets.UTF_8));
                os.close();
            }
        }
    }
}
