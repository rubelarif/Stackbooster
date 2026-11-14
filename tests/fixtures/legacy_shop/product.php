<?php
require_once 'includes/db.php';
include 'includes/header.php';

$id = (int)$_GET['id'];
$stmt = mysqli_prepare($conn, "SELECT id, name, description, price, stock FROM products WHERE id = ?");
mysqli_stmt_bind_param($stmt, 'i', $id);
mysqli_stmt_execute($stmt);
$product = mysqli_fetch_assoc(mysqli_stmt_get_result($stmt));
if (!$product) {
    header('Location: products.php');
    exit;
}
$reviews = db_all($conn, "SELECT r.rating, r.body, u.name FROM reviews r, users u WHERE r.user_id = u.id AND r.product_id = $id");
?>
<h1 id="product-name"><?= htmlspecialchars($product['name']) ?></h1>
<p><?= $product['description'] ?></p>
<button id="add-to-cart" data-id="<?= $product['id'] ?>">Add to cart</button>
<div id="reviews">
<?php foreach ($reviews as $r): ?>
  <blockquote><?= $r['body'] ?> - <?= $r['name'] ?></blockquote>
<?php endforeach; ?>
</div>
<script>
  $('#add-to-cart').click(function () {
    $.post('api.php?action=add_to_cart', { product_id: $(this).data('id'), quantity: 1 }, function (data) {
      $('#cart-count').text(data.count);
    }, 'json');
  });
</script>
<?php include 'includes/footer.php'; ?>
