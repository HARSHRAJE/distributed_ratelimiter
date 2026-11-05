import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPairGenerator;
import java.util.Base64;

public class GenerateRsaKeys {

    public static void main(String[] args) throws Exception {
        if (args.length != 1) {
            throw new IllegalArgumentException(
                "Usage: java GenerateRsaKeys.java <key-directory>"
            );
        }

        Path directory = Path.of(args[0]).toAbsolutePath().normalize();
        Files.createDirectories(directory);
        Path privateKeyPath = directory.resolve("auth-private.pem");
        Path publicKeyPath = directory.resolve("auth-public.pem");
        if (Files.exists(privateKeyPath) || Files.exists(publicKeyPath)) {
            throw new IllegalStateException(
                "Refusing to overwrite an existing Auth Service key"
            );
        }

        KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA");
        generator.initialize(2048);
        var keyPair = generator.generateKeyPair();
        Files.writeString(
            privateKeyPath,
            toPem("PRIVATE KEY", keyPair.getPrivate().getEncoded())
        );
        Files.writeString(
            publicKeyPath,
            toPem("PUBLIC KEY", keyPair.getPublic().getEncoded())
        );

        System.out.println("Wrote Auth Service keys to " + directory);
        System.out.println("Keep auth-private.pem outside source control.");
    }

    private static String toPem(String label, byte[] encoded) {
        return "-----BEGIN " + label + "-----\n"
            + Base64.getMimeEncoder(64, new byte[] {'\n'})
                .encodeToString(encoded)
            + "\n-----END " + label + "-----\n";
    }
}
