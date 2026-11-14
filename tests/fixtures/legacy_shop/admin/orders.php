<?php
session_start();
require_once '../includes/db.php';

if (empty($_SESSION['is_admin'])) {
    header('Location: ../login.php');
    exit;
}

if (isset($_POST['order_id'], $_POST['status'])) {
    $order_id = (int)$_POST['order_id'];
    $status = mysqli_real_escape_string($conn, $_POST['status']);
    mysqli_query($conn, "UPDATE orders SET status = '$status' WHERE id = $order_id");
}

$filter = isset($_GET['status']) ? $_GET['status'] : 'new';
$orders = db_all($conn, "SELECT o.id, o.full_name, o.status, o.created_at FROM orders o WHERE o.status = '" . mysqli_real_escape_string($conn, $filter) . "' ORDER BY o.created_at DESC");
?>
<html>
<head><title>Orders - Admin</title></head>
<body>
<h1>Orders</h1>
<table>
<?php foreach ($orders as $o): ?>
  <tr>
    <td><?= $o['id'] ?></td>
    <td><?= htmlspecialchars($o['full_name']) ?></td>
    <td>
      <form method="post" action="orders.php">
        <input type="hidden" name="order_id" value="<?= $o['id'] ?>">
        <select name="status">
          <option>new</option><option>shipped</option><option>cancelled</option>
        </select>
        <input type="submit" value="Save">
      </form>
    </td>
  </tr>
<?php endforeach; ?>
</table>
</body>
</html>
