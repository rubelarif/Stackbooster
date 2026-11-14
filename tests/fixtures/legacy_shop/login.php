<?php
$page_title = 'Log in';
require_once 'includes/db.php';
include 'includes/header.php';

$error = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $stmt = mysqli_prepare($conn, "SELECT id, password_hash FROM users WHERE email = ?");
    mysqli_stmt_bind_param($stmt, 's', $_POST['email']);
    mysqli_stmt_execute($stmt);
    $user = mysqli_fetch_assoc(mysqli_stmt_get_result($stmt));
    if ($user && md5($_POST['password']) === $user['password_hash']) {
        $_SESSION['user_id'] = $user['id'];
        header('Location: index.php');
        exit;
    }
    $error = 'Wrong email or password';
}
?>
<h1>Log in</h1>
<?php if ($error): ?><p class="error"><?= $error ?></p><?php endif; ?>
<form method="post">
  <input type="email" name="email" required>
  <input type="password" name="password" required>
  <input type="submit" value="Log in">
</form>
<?php include 'includes/footer.php'; ?>
