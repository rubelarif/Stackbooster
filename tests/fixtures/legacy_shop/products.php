<?php
$page_title = 'Products';
require_once 'includes/db.php';
include 'includes/header.php';

$category = isset($_GET['category']) ? $_GET['category'] : '';
$page = isset($_GET['page']) ? (int)$_GET['page'] : 1;
$q = isset($_GET['q']) ? $_GET['q'] : '';
$offset = ($page - 1) * 20;

// Old code builds SQL by concatenation.
$sql = "SELECT p.id, p.name, p.price, c.name AS category FROM products p "
     . "LEFT JOIN categories c ON c.id = p.category_id WHERE 1=1";
if ($category !== '') {
    $sql .= " AND c.slug = '" . $category . "'";
}
if ($q !== '') {
    $sql .= " AND p.name LIKE '%" . $q . "%'";
}
$sql .= " LIMIT $offset, 20";
$products = db_all($conn, $sql);
$categories = db_all($conn, "SELECT id, slug, name FROM categories ORDER BY name");
?>
<h1>Products</h1>
<form method="get" action="products.php">
  <select name="category">
    <option value="">All</option>
    <?php foreach ($categories as $c): ?>
      <option value="<?= $c['slug'] ?>"><?= $c['name'] ?></option>
    <?php endforeach; ?>
  </select>
  <input type="text" name="q" value="<?= htmlspecialchars($q) ?>">
  <button type="submit">Filter</button>
</form>
<table id="product-list">
<?php foreach ($products as $p): ?>
  <tr>
    <td><a href="product.php?id=<?= $p['id'] ?>"><?= $p['name'] ?></a></td>
    <td><?= $p['category'] ?></td>
    <td><?= $p['price'] ?></td>
  </tr>
<?php endforeach; ?>
</table>
<?php include 'includes/footer.php'; ?>
