<?php session_start(); ?>
<!DOCTYPE html>
<html>
<head>
  <title><?php echo isset($page_title) ? $page_title : 'Corner Shop'; ?></title>
  <link rel="stylesheet" href="/css/site.css">
  <script src="/js/jquery-1.8.3.min.js"></script>
  <script src="/js/cart.js"></script>
</head>
<body>
<div id="header">
  <a href="index.php">Home</a>
  <a href="products.php">Products</a>
  <a href="cart.php">Cart (<span id="cart-count">0</span>)</a>
  <?php if (isset($_SESSION['user_id'])): ?>
    <a href="logout.php">Log out</a>
  <?php else: ?>
    <a href="login.php">Log in</a>
  <?php endif; ?>
</div>
<div id="content">
