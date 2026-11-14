<?php
$page_title = 'Welcome';
require_once 'includes/db.php';
include 'includes/header.php';

$featured = db_all($conn, "SELECT id, name, price, image FROM products WHERE featured = 1 ORDER BY created_at DESC LIMIT 8");
?>
<h1>Featured products</h1>
<ul class="product-grid">
<?php foreach ($featured as $p): ?>
  <li>
    <a href="product.php?id=<?= $p['id'] ?>"><?= htmlspecialchars($p['name']) ?></a>
    <span class="price"><?= $p['price'] ?></span>
  </li>
<?php endforeach; ?>
</ul>
<form action="products.php" method="get" id="search-form">
  <input type="text" name="q" placeholder="Search">
  <input type="submit" value="Go">
</form>
<?php include 'includes/footer.php'; ?>
