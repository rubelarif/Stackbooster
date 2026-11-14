<?php
$page_title = 'Your cart';
require_once 'includes/db.php';
include 'includes/header.php';

$sid = session_id();
$items = db_all($conn, "SELECT c.id, c.quantity, p.name, p.price FROM cart_items c INNER JOIN products p ON p.id = c.product_id WHERE c.session_id = '$sid'");
$total = cart_total($conn, $sid);
?>
<h1>Your cart</h1>
<table id="cart-items">
<?php foreach ($items as $item): ?>
  <tr data-item="<?= $item['id'] ?>">
    <td><?= $item['name'] ?></td>
    <td><?= $item['quantity'] ?></td>
    <td><a href="#" class="remove-item">Remove</a></td>
  </tr>
<?php endforeach; ?>
</table>
<p>Total: <?= $total ?></p>
<form action="checkout.php" method="post" id="checkout-form">
  <input type="text" name="full_name" required>
  <input type="email" name="email" required>
  <textarea name="address" required></textarea>
  <input type="text" name="coupon">
  <input type="submit" value="Place order">
</form>
<?php include 'includes/footer.php'; ?>
