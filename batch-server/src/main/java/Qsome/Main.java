package Qsome;

import org.json.JSONObject;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeoutException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.nio.charset.StandardCharsets; 

public class Main {
    // Configuration for the Relay Server and Node ID
    private static final String RELAY_SERVER_URL = "http://localhost:8000/api/"; 
    private static final String OAUTH2_TOKEN_URL = "http://localhost:8000/o/token/"; 
    private static final String NODE_ID = "ABC123"; 
    private static final String ORCHESTRATOR_DOWNLOAD_DIR = "orchestrator_downloads";

    // IMPORTANT: Replace with your actual Client ID and Client Secret from Django Admin
    private static final String OAUTH2_CLIENT_ID = ""; 
    private static final String OAUTH2_CLIENT_SECRET = ""; 

    private static Node rpaOrchestratorNode; 

    public static void main(String[] args) {
        System.out.println("--- Starting RPA Orchestrator Test Flow ---");

        File downloadDir = new File(ORCHESTRATOR_DOWNLOAD_DIR);
        if (!downloadDir.exists()) {
            downloadDir.mkdirs();
            System.out.println("Created orchestrator download directory: " + downloadDir.getAbsolutePath());
        }

        try {
            String accessToken = getAccessTokenClientCredentials();
            if (accessToken == null) {
                System.err.println("Failed to obtain OAuth2 access token. Exiting.");
                return;
            }
            // MODIFIED: Print full access token
            System.out.println("Successfully obtained OAuth2 Access Token: " + accessToken); 

            JSONObject nodeAttrs = new JSONObject();
            nodeAttrs.put("os", System.getProperty("os.name"));
            nodeAttrs.put("java_version", System.getProperty("java.version"));
            nodeAttrs.put("client_type", "Java Orchestrator Test Harness");
            
            rpaOrchestratorNode = new Node("JavaOrchestrator", nodeAttrs, RELAY_SERVER_URL, "java_batch", accessToken);
            System.out.println("Orchestrator Node initialized. Waiting for Python client to connect...");

            Thread.sleep(5000); 

            System.out.println("\n--- Testing Mouse and Keyboard Commands ---");
            testMouseMove();
            testScroll();
            testTypeText();
            testClick();
            
            System.out.println("\n--- Testing File Transfer Commands ---");
            testSendFileToRPA(); 
            testScreenshot();     
            testGetFileFromRPA(); 

        } catch (Exception e) {
            System.err.println("An error occurred during the test flow: " + e.getMessage());
            e.printStackTrace();
        } finally {
            if (rpaOrchestratorNode != null) {
                rpaOrchestratorNode.disconnect();
            }
            System.out.println("\n--- RPA Orchestrator Test Flow Complete ---");
        }
    }

    private static String getAccessTokenClientCredentials() {
        HttpClient client = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(10))
                .build();

        String requestBody = String.format(
            "grant_type=client_credentials&client_id=%s&client_secret=%s",
            OAUTH2_CLIENT_ID, OAUTH2_CLIENT_SECRET
        );

        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(OAUTH2_TOKEN_URL))
                .header("Content-Type", "application/x-www-form-urlencoded") 
                .POST(HttpRequest.BodyPublishers.ofString(requestBody, StandardCharsets.UTF_8))
                .build();

        try {
            HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());

            if (response.statusCode() == 200) {
                JSONObject jsonResponse = new JSONObject(response.body());
                String accessToken = jsonResponse.optString("access_token");
                if (accessToken != null && !accessToken.isEmpty()) {
                    return accessToken; // Return full token to be printed by main
                } else {
                    System.err.println("OAuth2 Token response missing 'access_token'. Body: " + response.body());
                    return null;
                }
            } else {
                System.err.println("Failed to get OAuth2 token. Status: " + response.statusCode() + ", Body: " + response.body());
                return null;
            }
        } catch (IOException | InterruptedException e) {
            System.err.println("Error during OAuth2 token acquisition: " + e.getMessage());
            e.printStackTrace();
            return null;
        }
    }

    private static JSONObject sendCommandAndAwaitResponse(String commandType, Map<String, Object> params) throws Exception {
        System.out.println(String.format("\nSending command '%s' to node %s...", commandType, NODE_ID));
        
        JSONObject commandPayload = new JSONObject();
        commandPayload.put("commandType", commandType);
        commandPayload.put("params", new JSONObject(params));

        JSONObject finalResponse = rpaOrchestratorNode.sendRPACommand(NODE_ID, commandPayload);

        if (rpaOrchestratorNode.isRPACommandSuccessful(finalResponse)) {
            System.out.println(String.format("Command '%s' completed successfully.", commandType));
            JSONObject rpaResponsePayload = rpaOrchestratorNode.getRPACommandResponsePayload(finalResponse);
            System.out.println("RPA Response: " + rpaResponsePayload.toString());
            return finalResponse;
        } else {
            System.err.println(String.format("Command '%s' failed. Full response: %s", commandType, finalResponse.toString()));
            throw new RuntimeException(String.format("Command '%s' failed.", commandType));
        }
    }

    private static void testMouseMove() throws Exception {
        Map<String, Object> params = new HashMap<>();
        params.put("x", 100);
        params.put("y", 200);
        params.put("duration", 0.5); 
        sendCommandAndAwaitResponse("mouse_move", params);
    }

    private static void testScroll() throws Exception {
        Map<String, Object> params = new HashMap<>();
        params.put("clicks", 5); 
        sendCommandAndAwaitResponse("mouse_scroll", params);
    }

    private static void testTypeText() throws Exception {
        Map<String, Object> params = new HashMap<>();
        params.put("text", "Hello from Java Orchestrator!");
        sendCommandAndAwaitResponse("type_text", params);
    }

    private static void testClick() throws Exception {
        Map<String, Object> params = new HashMap<>();
        params.put("x", 500);
        params.put("y", 500);
        params.put("button", 1024); 
        sendCommandAndAwaitResponse("mouse_click", params);
    }

    private static void testSendFileToRPA() throws Exception {
        System.out.println("\n--- Testing sending a file from Orchestrator to RPA Client ---");
        String localSourceFilePath = ORCHESTRATOR_DOWNLOAD_DIR + File.separator + "orchestrator_upload_test.txt";
        String fileContent = "This file was sent from the Java Orchestrator to the RPA client.";
        Files.write(new File(localSourceFilePath).toPath(), fileContent.getBytes());
        System.out.println("Created dummy file to send: " + localSourceFilePath);

        File sourceFile = new File(localSourceFilePath);
        String rpaClientDestinationFileName = "received_from_java_orchestrator.txt";

        JSONObject response = rpaOrchestratorNode.sendFileToRPAClient(NODE_ID, sourceFile, rpaClientDestinationFileName);

        if (rpaOrchestratorNode.isRPACommandSuccessful(response)) {
            System.out.println("File successfully sent to RPA client. Response: " + response.toString());
        } else {
            System.err.println("Failed to send file to RPA client. Response: " + response.toString());
            throw new RuntimeException("File send failed.");
        }
    }

    private static void testScreenshot() throws Exception {
        System.out.println("\n--- Testing screenshot command (RPA Client -> Orchestrator) ---");
        Map<String, Object> params = new HashMap<>();
        
        JSONObject screenshotResponse = sendCommandAndAwaitResponse("screenshot", params);

        if (screenshotResponse.optString("status").equalsIgnoreCase("file_uploaded")) {
            JSONObject fileDetails = rpaOrchestratorNode.getRPACommandResponsePayload(screenshotResponse);
            String filename = fileDetails.optString("filename");
            String base64Content = fileDetails.optString("file_content_base64");

            if (filename != null && !filename.isEmpty() && base64Content != null && !base64Content.isEmpty()) {
                JSONObject fileTransferPayload = new JSONObject();
                fileTransferPayload.put("filename", filename);
                fileTransferPayload.put("file_content_base64", base64Content);
                fileTransferPayload.put("request_id", screenshotResponse.optString("requestId")); 

                Path savedPath = Node.receiveFileAndSave(fileTransferPayload, ORCHESTRATOR_DOWNLOAD_DIR);
                System.out.println("Screenshot saved by Orchestrator to: " + savedPath.toAbsolutePath());
            } else {
                System.err.println("Screenshot response missing file content details.");
            }
        } else {
            System.err.println("Screenshot command did not return expected 'file_uploaded' status.");
        }
    }

    private static void testGetFileFromRPA() throws Exception {
        System.out.println("\n--- Testing get_file command (RPA Client -> Orchestrator) ---");
        // MODIFIED: Changed backslashes to forward slashes for cross-platform compatibility and to fix Java escape sequence error
        String rpaClientSourceFilePath = "C:/Users/vaidh/Downloads/DSA Practice.xlsx"; 
        
        Map<String, Object> params = new HashMap<>();
        params.put("filePath", rpaClientSourceFilePath);

        JSONObject getFileResponse = sendCommandAndAwaitResponse("get_file", params);

        if (getFileResponse.optString("status").equalsIgnoreCase("file_uploaded")) {
            JSONObject fileDetails = rpaOrchestratorNode.getRPACommandResponsePayload(getFileResponse);
            String filename = fileDetails.optString("filename");
            String base64Content = fileDetails.optString("file_content_base64");

            if (filename != null && !filename.isEmpty() && base64Content != null && !base64Content.isEmpty()) {
                JSONObject fileTransferPayload = new JSONObject();
                fileTransferPayload.put("filename", filename);
                fileTransferPayload.put("file_content_base64", base64Content);
                fileTransferPayload.put("request_id", getFileResponse.optString("requestId")); 

                Path savedPath = Node.receiveFileAndSave(fileTransferPayload, ORCHESTRATOR_DOWNLOAD_DIR);
                System.out.println("File from RPA client saved by Orchestrator to: " + savedPath.toAbsolutePath());
            } else {
                System.err.println("Get File response missing file content details.");
            }
        } else {
            System.err.println("Get File command did not return expected 'file_uploaded' status.");
        }
    }
}
